from __future__ import annotations

import time as time_module
from pathlib import Path
from typing import Sequence
from publication import PublicationAttempt, PublicationReceipt, perform_upload

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


def upload_videos(videos: Sequence[dict[str, object]], caption_limit: int = INSTAGRAM_CAPTION_MAX_CHARS,
                  *, on_submitting=None, on_confirmed=None) -> list[PublicationReceipt]:
    """Return explicit receipts. Never retry a potentially submitted publication."""
    from playwright.sync_api import TimeoutError, sync_playwright
    if not videos:
        return []
    receipts = []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(INSTAGRAM_USER_DATA_DIR),
            channel="chrome",
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
            for video in videos:
                video_path = Path(str(video["video_path"])).resolve()
                if not video_path.is_file():
                    raise FileNotFoundError(f"Video nao encontrado em {video_path}")
                title = str(video["title"])
                description = str(video.get("description", title))
                tags = [str(tag) for tag in video.get("tags", [])]
                _open_upload_home(page)
                _ensure_logged_in(page, TimeoutError)
                caption = build_social_caption(title, description, limit=caption_limit, tags=tags)
                publication = PublicationAttempt(
                    "instagram",
                    (lambda: on_submitting(video)) if on_submitting else None,
                    (lambda receipt: on_confirmed(video, receipt)) if on_confirmed else None,
                )
                receipts.append(perform_upload(lambda: _upload_single_video(page, video_path, caption, publication), publication))
        finally:
            context.close()
    return receipts

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

def _upload_single_video(page, video_file: Path, caption: str, publication: PublicationAttempt) -> None:
    print("Iniciando fluxo de upload no Instagram...")

    # Fechar popups genéricos que atrapalham
    _dismiss_generic_popups(page)

    # 1. Clicar em Criar — múltiplas estratégias
    print("Abrindo modal de criação...")
    modal_opened = False

    # Helper: tenta clicar no submenu "Postar" se um dropdown apareceu
    def _try_click_postar_dropdown():
        """Após clicar em 'Criar', o Instagram pode abrir um dropdown
        com opções 'Postar' e 'IA'. Precisamos clicar em 'Postar'."""
        dropdown_texts = ['Postar', 'Publicação', 'Post', 'Create post']
        for txt in dropdown_texts:
            try:
                for tag in ['span', 'a', 'div']:
                    loc = page.locator(f"{tag}:text-is('{txt}')").first
                    if loc.is_visible(timeout=1000):
                        loc.click(timeout=3000)
                        page.wait_for_timeout(2000)
                        return True
            except Exception:
                continue
        return False

    # Estratégia A: Clique no link da sidebar + dropdown
    create_selectors = [
        "a:has-text('Criar')",
        "a:has-text('Create')",
        "[aria-label='Nova publicação']",
        "[aria-label='New post']",
        "[aria-label='Criar']",
        "[aria-label='Create']",
        "svg[aria-label='Nova publicação']",
        "svg[aria-label='New post']",
    ]

    for sel in create_selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=2000):
                # Tentar clique nativo primeiro
                loc.click(timeout=5000)
                page.wait_for_timeout(2000)

                # Verificar se o modal abriu direto (sem dropdown)
                if page.locator("input[type='file']").count() > 0:
                    modal_opened = True
                    print(f"Modal aberto diretamente via: {sel}")
                    break

                # Se não abriu, provavelmente apareceu o dropdown — clicar em "Postar"
                if _try_click_postar_dropdown():
                    if page.locator("input[type='file']").count() > 0:
                        modal_opened = True
                        print(f"Modal aberto via dropdown 'Postar' após: {sel}")
                        break

                # Último recurso: dispatch_event
                loc.dispatch_event("click")
                page.wait_for_timeout(2000)
                _try_click_postar_dropdown()
                page.wait_for_timeout(1000)
                if page.locator("input[type='file']").count() > 0:
                    modal_opened = True
                    print(f"Modal aberto via dispatch_event em: {sel}")
                    break
        except Exception:
            continue

    # Estratégia B: JavaScript puro
    if not modal_opened:
        print("Tentando abrir modal via JavaScript...")
        try:
            page.evaluate('''() => {
                const links = document.querySelectorAll('a, div[role="button"], span');
                for (const el of links) {
                    const txt = (el.textContent || '').trim();
                    if (txt === 'Criar' || txt === 'Create') {
                        el.click();
                        return true;
                    }
                }
                return false;
            }''')
            page.wait_for_timeout(2000)
            _try_click_postar_dropdown()
            page.wait_for_timeout(1000)
            if page.locator("input[type='file']").count() > 0:
                modal_opened = True
                print("Modal aberto via JavaScript puro.")
        except Exception:
            pass

    if not modal_opened:
        _save_debug_screenshot(page, "instagram_modal_failed")
        raise RuntimeError(
            "Não foi possível abrir o modal de criação do Instagram. "
            "O botão 'Criar' não respondeu ao clique."
        )

    # 2. Upload do arquivo via input[type=file]
    print("Injetando arquivo de vídeo...")
    file_input = page.locator("input[type='file']").first
    try:
        file_input.wait_for(state="attached", timeout=10000)
        # Aceitar todos os tipos de arquivo (o Instagram pode restringir via accept)
        page.evaluate('''() => {
            const inputs = document.querySelectorAll('input[type="file"]');
            inputs.forEach(i => i.removeAttribute("accept"));
        }''')
        file_input.set_files(str(video_file))
        print("Arquivo injetado via input[type=file].")
    except Exception:
        print("Fallback: usando file chooser...")
        try:
            with page.expect_file_chooser(timeout=10000) as file_chooser_info:
                select_btn = _first_visible_locator(
                    page,
                    [
                        "button:has-text('Selecionar do computador')",
                        "button:has-text('Select from computer')",
                        "div[role='button']:has-text('Selecionar do computador')",
                        "div[role='button']:has-text('Select from computer')",
                        "text=Selecionar do computador",
                        "text=Select from computer",
                    ],
                    timeout_ms=10000,
                )
                select_btn.click(timeout=10000, force=True)
            file_chooser_info.value.set_files(str(video_file))
            print("Arquivo injetado via file chooser.")
        except Exception as exc:
            _save_debug_screenshot(page, "instagram_file_inject_failed")
            raise RuntimeError(
                f"Não foi possível injetar o arquivo de vídeo no Instagram: {exc}"
            )

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

    _click_share_button(page, publication)
    _wait_for_share_confirmation(page, publication)
    _close_confirmation_modal(page)


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


def _click_share_button(page, publication: PublicationAttempt) -> None:
    button = _first_visible_locator(page, [
        "div[role='button']:text-is('Compartilhar')", "button:text-is('Compartilhar')",
        "div[role='button']:text-is('Share')", "button:text-is('Share')",
    ], timeout_ms=15000)
    publication.before_submit(page)
    button.click(timeout=30000)


def _wait_for_share_confirmation(page, publication: PublicationAttempt, timeout_ms: int = 120000):
    return publication.confirm(page, timeout_ms)


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
