from __future__ import annotations

import time as time_module
from pathlib import Path
from typing import Sequence

from utils import build_social_caption
from config import (
    RETRY_ATTEMPTS,
    RETRY_DELAY_SECONDS,
    INSTAGRAM_CAPTION_MAX_CHARS,
    INSTAGRAM_URL,
    INSTAGRAM_USER_DATA_DIR,
    HEADLESS_MODE,
    BASE_DIR,
)

# Pasta de screenshots de depuração (NÃO é limpa pelo main.py)
DEBUG_SCREENSHOTS_DIR = BASE_DIR / "debug_screenshots"


def upload_videos(
    videos: Sequence[dict[str, object]],
    caption_limit: int = INSTAGRAM_CAPTION_MAX_CHARS,
) -> list[str]:
    """
    Faz upload em lote para o Instagram Reels.
    """
    try:
        from playwright.sync_api import TimeoutError, sync_playwright
    except ImportError:
        raise ImportError(
            "O pacote 'playwright' não está instalado."
        )

    if not videos:
        return []

    print("Iniciando automação em lote do Instagram...")
    uploaded_refs: list[str] = []
    failed_refs: list[str] = []
    attempts = max(1, int(RETRY_ATTEMPTS))
    delay_seconds = max(0.0, float(RETRY_DELAY_SECONDS))

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(INSTAGRAM_USER_DATA_DIR),
            headless=HEADLESS_MODE,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--mute-audio",
                # Evita o popup "Restaurar páginas? O Chromium não foi encerrado corretamente."
                "--disable-session-crashed-bubble",
                "--hide-crash-restore-bubble",
                "--no-default-browser-check",
                "--disable-gpu",
                "--disable-dev-shm-usage",
            ],
            locale="pt-BR",
        )

        try:
            page = context.new_page()
            
            for index, video in enumerate(videos, start=1):
                video_path = Path(str(video["video_path"])).resolve()
                if not video_path.exists():
                    raise FileNotFoundError(f"Vídeo não encontrado em {video_path}")

                title = str(video["title"])
                description = str(video.get("description", title))
                caption = build_social_caption(title, description, limit=caption_limit)

                print(f"Enviando Reel {index}/{len(videos)} para o Instagram: {title}...")
                video_uploaded = False

                for attempt in range(1, attempts + 1):
                    try:
                        _open_upload_home(page)
                        _ensure_logged_in(page, TimeoutError)
                        
                        _upload_single_video(
                            page=page,
                            video_file=video_path,
                            caption=caption,
                        )
                        uploaded_refs.append(title)
                        video_uploaded = True
                        break
                    except Exception as exc:
                        _save_debug_screenshot(page, f"instagram_attempt_{attempt}")
                        if attempt >= attempts:
                            print(f"Falha final ao enviar '{title}' ao Instagram: {exc}")
                            break
                        print(
                            f"Falha ao enviar '{title}' no Instagram na tentativa {attempt}/{attempts}: {exc}"
                        )
                        if delay_seconds:
                            print(f"Tentando novamente em {delay_seconds:.0f} segundos...")
                            time_module.sleep(delay_seconds)

                if not video_uploaded:
                    failed_refs.append(title)

        finally:
            print("Fechando navegador Instagram automaticamente...")
            context.close()

    return uploaded_refs

def _open_upload_home(page) -> None:
    page.goto(INSTAGRAM_URL)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(3000)
    # Fechar qualquer popup do Chrome de restauração
    _dismiss_chrome_restore(page)

def _dismiss_chrome_restore(page) -> None:
    """Fecha o popup 'Restaurar páginas?' do Chromium se existir."""
    try:
        # O popup de restauração pode aparecer como um infobar do Chrome
        # Tenta fechar via tecla Escape ou clicando no X
        restore_selectors = [
            "button:has-text('Restaurar')",
            "button:has-text('Restore')",
        ]
        for sel in restore_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    # NÃO clicar em Restaurar — queremos ignorar
                    # Pressionar Escape para fechar
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)
                    print("Popup de restauração do Chromium descartado.")
                    return
            except Exception:
                continue
    except Exception:
        pass

def _ensure_logged_in(page, timeout_error) -> None:
    try:
        _first_visible_locator(
            page,
            [
                "span:has-text('Criar')",
                "span:has-text('Create')",
                "a:has-text('Criar')",
                "a:has-text('Create')",
                "svg[aria-label='Nova publicação']",
                "svg[aria-label='New post']",
                "[aria-label='Criar']",
                "[aria-label='Nova publicação']",
                "[aria-label='Create']",
                "[aria-label='New post']"
            ],
            timeout_ms=10000,
        )
        print("Login detectado no Instagram!")
        return
    except timeout_error:
        pass

    print("\n*** LOGIN NECESSÁRIO NO INSTAGRAM ***")
    print("Por favor, faça login na janela do navegador.")
    _first_visible_locator(
        page,
        [
            "span:has-text('Criar')",
            "span:has-text('Create')",
            "a:has-text('Criar')",
            "a:has-text('Create')",
            "svg[aria-label='Nova publicação']",
            "svg[aria-label='New post']",
            "[aria-label='Criar']",
            "[aria-label='Nova publicação']",
            "[aria-label='Create']",
            "[aria-label='New post']"
        ],
        timeout_ms=0,
    )
    print("Login do Instagram concluído com sucesso!")

def _upload_single_video(page, video_file: Path, caption: str) -> None:
    print("Iniciando fluxo de upload no Instagram...")

    # Fechar popups genéricos que atrapalham
    _dismiss_generic_popups(page)

    # 1. Clicar em Criar
    print("Abrindo modal de criação...")
    create_btn = _first_visible_locator(
        page,
        [
            "span:has-text('Criar')",
            "span:has-text('Create')",
            "svg[aria-label='Nova publicação']",
            "svg[aria-label='New post']",
            "[aria-label='Criar']",
            "[aria-label='Nova publicação']",
            "[aria-label='Create']",
            "[aria-label='New post']",
        ],
        timeout_ms=30000,
    )
    create_btn.click(timeout=10000, force=True)
    page.wait_for_timeout(3000)

    # 2. Upload do arquivo via input[type=file] (método mais confiável)
    print("Injetando arquivo de vídeo...")
    file_input = page.locator("input[type='file']").first
    try:
        file_input.wait_for(state="attached", timeout=10000)
        file_input.set_files(str(video_file))
        print("Arquivo injetado via input[type=file].")
    except Exception:
        print("Fallback: usando file chooser...")
        with page.expect_file_chooser() as file_chooser_info:
            select_btn = _first_visible_locator(
                page,
                [
                    "button:has-text('Selecionar do computador')",
                    "button:has-text('Select from computer')",
                    "text=Selecionar do computador",
                    "text=Select from computer",
                ],
                timeout_ms=10000,
            )
            select_btn.click(timeout=10000, force=True)
        file_chooser_info.value.set_files(str(video_file))
        print("Arquivo injetado via file chooser.")

    # Aguardar o Instagram processar o vídeo (loading/spinner)
    print("Aguardando Instagram processar o vídeo...")
    page.wait_for_timeout(5000)

    # *** NOVO: Fechar popup "Agora os posts de vídeo são compartilhados como reels" ***
    _dismiss_reels_info_popup(page)

    # Fechar qualquer outro popup que tenha surgido
    _dismiss_generic_popups(page)

    # Esperar que o botão Avançar/Next fique disponível (prova que o vídeo carregou)
    _first_visible_locator(
        page,
        [
            "div[role='button']:has-text('Avançar')",
            "button:has-text('Avançar')",
            "div[role='button']:has-text('Next')",
            "button:has-text('Next')",
        ],
        timeout_ms=60000,
    )

    # 3. Avançar — Cortar (Crop)
    print("Avançando (Cortar)...")
    _click_next(page)
    page.wait_for_timeout(3000)

    # *** NOVO: Fechar popup de reels se aparecer neste ponto ***
    _dismiss_reels_info_popup(page)

    # 4. Avançar — Editar (Foto da capa / Encurtar)
    print("Avançando (Editar)...")
    _click_next(page)
    page.wait_for_timeout(3000)

    # 5. Legenda — usar múltiplas estratégias
    # Verificar se estamos realmente na tela de legenda
    # Se ainda houver um botão "Avançar", clicar mais uma vez (filtros extras)
    try:
        extra_next = _first_visible_locator(
            page,
            [
                "div[role='button']:text-is('Avançar')",
                "button:text-is('Avançar')",
                "div[role='button']:text-is('Next')",
                "button:text-is('Next')",
            ],
            timeout_ms=3000,
        )
        # Se encontrou "Avançar" mas NÃO encontrou "Compartilhar", clicar mais uma vez
        try:
            page.locator("div[role='button']:text-is('Compartilhar')").first.is_visible(timeout=1000)
            # Se "Compartilhar" já está visível, estamos na tela certa
            print("Tela de legenda detectada (botão Compartilhar visível).")
        except Exception:
            print("Avançando (etapa extra)...")
            extra_next.click(timeout=5000, force=True)
            page.wait_for_timeout(3000)
    except Exception:
        pass  # Não tem mais "Avançar", provavelmente já estamos na legenda

    print("Preenchendo legenda...")
    _fill_instagram_caption(page, caption)
    page.wait_for_timeout(2000)

    # 6. Compartilhar — múltiplas estratégias de clique
    print("Clicando em Compartilhar...")
    _save_debug_screenshot(page, "ig_before_share_click")
    _click_share_button(page)

    # 7. Aguardar confirmação REAL de publicação
    print("Aguardando confirmação real do Instagram (até 120s)...")
    confirmed = _wait_for_share_confirmation(page, timeout_ms=120000)

    if confirmed:
        print("✅ Publicação confirmada pelo Instagram!")
    else:
        # Capturar screenshot para diagnóstico
        _save_debug_screenshot(page, "instagram_share_failed")
        raise RuntimeError(
            "Instagram não confirmou a publicação. O vídeo pode não ter sido "
            "publicado. Verifique a conta manualmente."
        )

    # Fechar o modal de confirmação
    _close_confirmation_modal(page)

    print("Upload concluído com sucesso via Instagram!")


def _dismiss_generic_popups(page) -> None:
    """Fecha popups genéricos do Instagram ('Agora não', 'Not Now', etc.)."""
    for popup_text in ("Agora não", "Not Now", "Não agora", "Fechar", "Close"):
        try:
            popup = page.locator(f"button:has-text('{popup_text}')").first
            if popup.is_visible(timeout=1500):
                popup.click(force=True)
                print(f"Popup '{popup_text}' fechado.")
                page.wait_for_timeout(1000)
        except Exception:
            pass


def _dismiss_reels_info_popup(page) -> None:
    """Fecha o popup informativo 'Agora os posts de vídeo são compartilhados como reels'."""
    reels_popup_selectors = [
        # Botão OK no popup de informação sobre Reels
        "button:has-text('OK')",
        "button:text-is('OK')",
        # Variação em inglês
        "button:has-text('Got it')",
        "button:text-is('Got it')",
        # Saiba mais sobre o Reels — pode ter um X para fechar
        "button:has-text('Saiba mais')",
    ]
    
    # Primeiro verificar se o texto do popup está visível
    try:
        popup_visible = False
        for text in ("compartilhados como reels", "shared as reels", "Saiba mais sobre o Reels"):
            try:
                el = page.locator(f"text={text}").first
                if el.is_visible(timeout=2000):
                    popup_visible = True
                    print(f"Popup de Reels detectado: '{text}'")
                    break
            except Exception:
                continue
        
        if popup_visible:
            # Tentar clicar no botão OK
            for sel in reels_popup_selectors:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=2000):
                        btn.click(force=True)
                        print(f"Popup de Reels fechado via: {sel}")
                        page.wait_for_timeout(2000)
                        return
                except Exception:
                    continue
            
            # Se não encontrou botão, tentar Escape
            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)
            print("Popup de Reels fechado via Escape.")
    except Exception:
        pass


def _fill_instagram_caption(page, caption: str) -> None:
    """Preenche a legenda usando múltiplas estratégias."""
    # Aguardar a página de legenda carregar completamente
    page.wait_for_timeout(2000)

    # Estratégia 1: Localizar pelo placeholder/aria-label específico do Instagram
    caption_selectors = [
        "div[aria-label*='legenda']",
        "div[aria-label*='caption']",
        "div[aria-label*='Escreva']",
        "div[aria-label*='Write']",
        "p[data-lexical-text='true']",
        "div[role='textbox'][contenteditable='true']",
        "div[contenteditable='true'][role='textbox']",
    ]
    for sel in caption_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3000):
                el.click(timeout=3000)
                page.wait_for_timeout(500)
                page.keyboard.insert_text(caption)
                print(f"Legenda preenchida via seletor: {sel}")
                return
        except Exception:
            continue

    # Estratégia 2: JS — buscar contenteditable que seja o campo de legenda
    # (filtra alt-text e outros campos menores)
    try:
        focused = page.evaluate('''() => {
            const editables = document.querySelectorAll('div[contenteditable="true"]');
            for (const el of editables) {
                // O campo de legenda geralmente tem aria-label ou placeholder
                const label = (el.getAttribute('aria-label') || '').toLowerCase();
                const role = (el.getAttribute('role') || '').toLowerCase();
                if (label.includes('legenda') || label.includes('caption') ||
                    label.includes('escreva') || label.includes('write') ||
                    role === 'textbox') {
                    el.focus();
                    el.click();
                    return 'aria-label match: ' + label;
                }
            }
            // Fallback: pegar o maior contenteditable (provavelmente a legenda)
            let biggest = null;
            let biggestArea = 0;
            for (const el of editables) {
                const rect = el.getBoundingClientRect();
                const area = rect.width * rect.height;
                if (area > biggestArea && rect.width > 100) {
                    biggest = el;
                    biggestArea = area;
                }
            }
            if (biggest) {
                biggest.focus();
                biggest.click();
                return 'biggest contenteditable';
            }
            return null;
        }''')
        if focused:
            page.wait_for_timeout(500)
            page.keyboard.insert_text(caption)
            print(f"Legenda preenchida via JS: {focused}")
            return
    except Exception as e:
        print(f"Estratégia JS falhou: {e}")

    # Estratégia 3: Tab para navegar até o campo de legenda
    try:
        page.keyboard.press("Tab")
        page.wait_for_timeout(500)
        page.keyboard.insert_text(caption)
        print("Legenda preenchida via Tab navigation.")
        return
    except Exception as e:
        print(f"Estratégia Tab falhou: {e}")

    print("⚠️ Não foi possível preencher a legenda — publicando sem legenda.")


def _click_share_button(page) -> None:
    """Clica no botão Compartilhar usando múltiplas estratégias."""
    share_selectors = [
        "div[role='button']:text-is('Compartilhar')",
        "button:text-is('Compartilhar')",
        "div[role='button']:text-is('Share')",
        "button:text-is('Share')",
        # Fallbacks em caso do texto exato falhar (ícones, etc)
        "div[role='button']:has-text('Compartilhar'):not(:has-text('primeira'))",
        "button:has-text('Compartilhar'):not(:has-text('primeira'))",
    ]

    share_btn = _first_visible_locator(page, share_selectors, timeout_ms=15000)

    # Esperar o botão estar habilitado
    try:
        page.wait_for_timeout(2000)
        is_disabled = share_btn.evaluate("el => el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true'")
        if is_disabled:
            print("Botão Compartilhar está desabilitado (vídeo processando ou legenda carregando). Aguardando ficar habilitado...")
            start_wait = time_module.monotonic()
            while time_module.monotonic() - start_wait < 30:
                page.wait_for_timeout(2000)
                is_disabled = share_btn.evaluate("el => el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true'")
                if not is_disabled:
                    print("Botão Compartilhar foi habilitado!")
                    break
            else:
                print("Aviso: Tempo limite de espera pelo botão habilitado excedido. Tentando clicar mesmo assim.")
    except Exception as e:
        print(f"Erro ao verificar se o botão está habilitado: {e}")

    # Estratégia 1: Clique normal (sem force)
    try:
        share_btn.click(timeout=5000)
        print("Botão Compartilhar clicado (método normal).")
        return
    except Exception as e:
        print(f"  [Estratégia 1] Clique normal falhou: {e}")

    # Estratégia 2: Force click
    try:
        share_btn.click(timeout=5000, force=True)
        print("Botão Compartilhar clicado (force=True).")
        return
    except Exception as e:
        print(f"  [Estratégia 2] force=True falhou: {e}")

    # Estratégia 3: JS click direto no elemento exato
    try:
        clicked = page.evaluate('''() => {
            const texts = ['Compartilhar', 'Share'];
            for (const text of texts) {
                const elements = document.querySelectorAll('div[role="button"], button');
                for (const el of elements) {
                    const txt = el.textContent.trim();
                    if (txt === text) {
                        // Verificar se não é o botão de background "Compartilhe sua primeira foto"
                        if (el.closest('[role="dialog"]') || el.closest('[role="presentation"]')) {
                            el.click();
                            return 'clicked: ' + txt;
                        }
                    }
                }
            }
            // Fallback: clicar no primeiro que tenha texto exato
            for (const text of texts) {
                const elements = document.querySelectorAll('div[role="button"], button');
                for (const el of elements) {
                    const txt = el.textContent.trim();
                    if (txt === text && !txt.toLowerCase().includes('primeira')) {
                        el.click();
                        return 'fallback clicked: ' + txt;
                    }
                }
            }
            return null;
        }''')
        if clicked:
            print(f"Botão Compartilhar clicado (via JS direto: {clicked}).")
            return
    except Exception as e:
        print(f"  [Estratégia 3] JS click falhou: {e}")

    # Estratégia 4: dispatch_event (último recurso)
    try:
        share_btn.dispatch_event("click")
        print("Botão Compartilhar clicado (dispatch_event).")
        return
    except Exception as e:
        print(f"  [Estratégia 4] dispatch_event falhou: {e}")

    print("⚠️ Todas as estratégias de clique falharam!")


def _wait_for_share_confirmation(page, timeout_ms: int = 120000) -> bool:
    """Espera a confirmação real de que o post foi publicado."""
    try:
        DEBUG_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(DEBUG_SCREENSHOTS_DIR / "debug_ig_before_confirm.png"))
    except Exception:
        pass

    # Textos de confirmação que o Instagram exibe quando o reel é publicado
    confirmation_texts = [
        "Seu reel foi compartilhado",
        "Your reel has been shared",
        "Sua publicação foi compartilhada",
        "Your post has been shared",
        "Reel compartilhado",
        "Reel shared",
    ]

    try:
        _first_visible_locator(
            page,
            [f"text={t}" for t in confirmation_texts],
            timeout_ms=timeout_ms,
        )
        try:
            page.screenshot(path=str(DEBUG_SCREENSHOTS_DIR / "debug_ig_success_modal.png"))
        except Exception:
            pass
        return True
    except Exception:
        pass

    # Fallback: Verificar se o modal "Compartilhamento" (sharing options) apareceu
    # Esse modal com "Copiar link", "Facebook", "WhatsApp" etc. aparece APÓS
    # o post ser publicado com sucesso
    try:
        sharing_modal = _first_visible_locator(
            page,
            [
                "text=Compartilhamento",
                "text=Sharing",
                "text=Copiar link",
                "text=Copy link",
            ],
            timeout_ms=5000,
        )
        if sharing_modal:
            print("Modal de compartilhamento social detectado — publicação provavelmente realizada!")
            try:
                page.screenshot(path=str(DEBUG_SCREENSHOTS_DIR / "debug_ig_sharing_modal.png"))
            except Exception:
                pass
            return True
    except Exception:
        pass

    # Capturar screenshot do estado final
    try:
        page.screenshot(path=str(DEBUG_SCREENSHOTS_DIR / "debug_ig_failed_modal.png"))
    except Exception:
        pass

    return False


def _close_confirmation_modal(page) -> None:
    """Tenta fechar o modal de confirmação/compartilhamento do Instagram."""
    close_selectors = [
        "svg[aria-label='Fechar']",
        "svg[aria-label='Close']",
        "button[aria-label='Fechar']",
        "button[aria-label='Close']",
        # O X no topo do modal de compartilhamento
        "[role='dialog'] svg[aria-label='Fechar']",
        "[role='dialog'] svg[aria-label='Close']",
    ]
    for sel in close_selectors:
        try:
            close_btn = page.locator(sel).first
            if close_btn.is_visible(timeout=3000):
                close_btn.click(force=True)
                page.wait_for_timeout(1000)
                print("Modal de confirmação fechado.")
                return
        except Exception:
            continue
    
    # Fallback: tentar Escape para fechar qualquer modal
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass


def _save_debug_screenshot(page, name: str) -> None:
    """Salva screenshot para diagnóstico em caso de falha."""
    try:
        DEBUG_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        screenshot_path = DEBUG_SCREENSHOTS_DIR / f"debug_{name}.png"
        page.screenshot(path=str(screenshot_path))
        print(f"📸 Screenshot de debug salvo: {screenshot_path}")
    except Exception:
        pass

def _click_next(page):
    next_btn = _first_visible_locator(
        page,
        [
            "div[role='button']:text-is('Avançar')",
            "button:text-is('Avançar')",
            "div[role='button']:text-is('Next')",
            "button:text-is('Next')",
            "div[role='button']:has-text('Avançar')",
            "button:has-text('Avançar')",
        ],
        timeout_ms=15000,
    )
    next_btn.click(timeout=5000, force=True)

def _first_visible_locator(page, selectors: Sequence[str], timeout_ms: int):
    deadline_seconds = timeout_ms / 1000.0
    start_time = time_module.monotonic()
    last_error: Exception | None = None

    while time_module.monotonic() - start_time <= deadline_seconds:
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = locator.count()
                for i in range(count):
                    nth_locator = locator.nth(i)
                    if nth_locator.is_visible():
                        return nth_locator
            except Exception as exc:
                last_error = exc
        page.wait_for_timeout(1000)

    raise RuntimeError(
        f"Não foi possível localizar elemento visível entre: {', '.join(selectors)}"
    ) from last_error
