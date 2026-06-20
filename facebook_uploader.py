from __future__ import annotations

import time as time_module
from pathlib import Path
from typing import Sequence
from utils import build_social_caption

from config import (
    BASE_DIR,
    RETRY_ATTEMPTS,
    RETRY_DELAY_SECONDS,
    FACEBOOK_CAPTION_MAX_CHARS,
    FACEBOOK_URL,
    FACEBOOK_USER_DATA_DIR,
    HEADLESS_MODE,
)

DEBUG_DIR = BASE_DIR / "debug_screenshots"


def upload_videos(
    videos: Sequence[dict[str, object]],
    caption_limit: int = FACEBOOK_CAPTION_MAX_CHARS,
) -> list[str]:
    """
    Faz upload em lote para o Facebook Reels.
    """
    try:
        from playwright.sync_api import TimeoutError, sync_playwright
    except ImportError:
        raise ImportError(
            "O pacote 'playwright' nao esta instalado."
        )

    if not videos:
        return []

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    print("Iniciando automacao em lote do Facebook Reels...")
    uploaded_refs: list[str] = []
    failed_refs: list[str] = []
    attempts = max(1, int(RETRY_ATTEMPTS))
    delay_seconds = max(0.0, float(RETRY_DELAY_SECONDS))

    chromium_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-notifications",
        "--mute-audio",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--no-default-browser-check",
    ]
    if HEADLESS_MODE:
        chromium_args.append("--window-position=20000,20000")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(FACEBOOK_USER_DATA_DIR),
            headless=False,
            args=chromium_args,
            locale="pt-BR",
            viewport={"width": 1280, "height": 900},
        )

        try:
            page = context.new_page()

            for index, video in enumerate(videos, start=1):
                video_path = Path(str(video["video_path"])).resolve()
                if not video_path.exists():
                    raise FileNotFoundError(f"Video nao encontrado em {video_path}")

                title = str(video["title"])
                description = str(video.get("description", title))
                caption = build_social_caption(title, description, limit=caption_limit)

                print(f"Enviando Video {index}/{len(videos)} para o Facebook Reels: {title}...")
                video_uploaded = False

                for attempt in range(1, attempts + 1):
                    try:
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
                        _save_debug_screenshot(page, f"fb_error_attempt_{attempt}")
                        if attempt >= attempts:
                            print(f"Falha final ao enviar '{title}' ao Facebook: {exc}")
                            break
                        print(
                            f"Falha ao enviar '{title}' no Facebook na tentativa {attempt}/{attempts}: {exc}"
                        )
                        if delay_seconds:
                            print(f"Tentando novamente em {delay_seconds:.0f} segundos...")
                            time_module.sleep(delay_seconds)

                if not video_uploaded:
                    failed_refs.append(title)

        finally:
            print("Fechando navegador Facebook automaticamente...")
            context.close()

    return uploaded_refs


def _save_debug_screenshot(page, label: str) -> None:
    try:
        path = DEBUG_DIR / f"debug_{label}.png"
        page.screenshot(path=str(path), full_page=False)
        print(f"Screenshot de debug salvo: {path}")
    except Exception:
        pass


def _ensure_logged_in(page, timeout_error) -> None:
    """Verifica se o usuario esta logado indo para a pagina home."""
    page.goto(FACEBOOK_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    
    logged_in_selectors = [
        "[aria-label='Facebook']",
        "[aria-label='Pesquisar no Facebook']",
        "[aria-label='Search Facebook']",
        "div[role='banner']",
    ]
    try:
        for sel in logged_in_selectors:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                print("Login detectado no Facebook!")
                return
        if "facebook.com" in page.url and "/login" not in page.url:
            print("Login detectado no Facebook (via URL)!")
            return
    except Exception:
        pass

    print("\n*** LOGIN NECESSARIO NO FACEBOOK ***")
    print("Por favor, faca login na janela do navegador.")
    while True:
        page.wait_for_timeout(3000)
        try:
            if "facebook.com" in page.url and "/login" not in page.url:
                for sel in logged_in_selectors:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        print("Login do Facebook concluido com sucesso!")
                        return
        except Exception:
            continue


def _upload_single_video(page, video_file: Path, caption: str) -> None:
    print("Iniciando fluxo de upload no Facebook Reels...")

    # 1. Navegar direto para criacao de Reels
    print("Acessando pagina de criacao de Reels...")
    page.goto("https://www.facebook.com/reels/create", wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    _save_debug_screenshot(page, "fb_reels_step1_opened")

    # 2. Anexar o video
    print("Anexando video...")
    _attach_video(page, video_file)
    print("Aguardando Facebook processar o video (10s)...")
    page.wait_for_timeout(10000)
    _save_debug_screenshot(page, "fb_reels_step2_attached")

    # 3. Clicar Avançar (do step 1 para step 2 - Editar Reel)
    print("Clicando Avançar (1/2)...")
    _click_avancar(page)
    page.wait_for_timeout(4000)
    _save_debug_screenshot(page, "fb_reels_step3_editar")

    # 4. Preencher legenda no passo "Editar Reel"
    print("Preenchendo legenda...")
    _fill_caption(page, caption)
    page.wait_for_timeout(2000)
    _save_debug_screenshot(page, "fb_reels_step4_caption")

    # 5. Clicar Avançar (do step 2 para step 3 - Configurações)
    print("Clicando Avançar (2/2)...")
    _click_avancar(page)
    page.wait_for_timeout(4000)
    _save_debug_screenshot(page, "fb_reels_step5_config")

    # 5.5 Definir publico como "Publico"
    print("Configurando privacidade para Publico...")
    _set_audience_to_public(page)
    _save_debug_screenshot(page, "fb_reels_step5_5_public_set")

    # 6. Publicar
    print("Publicando...")
    _click_publish(page)

    # 7. Aguardar confirmacao
    print("Aguardando upload finalizar...")
    _wait_for_upload_complete(page)

    print("Upload concluido com sucesso via Facebook Reels!")


def _click_avancar(page) -> None:
    """Clica no botão 'Avançar' ou 'Next'."""
    try:
        page.evaluate('''() => {
            const buttons = document.querySelectorAll('div[role="button"]');
            for (const btn of buttons) {
                const txt = (btn.innerText || '').trim();
                if (txt === 'Avançar' || txt === 'Next') {
                    btn.click();
                    return;
                }
            }
        }''')
    except Exception as e:
        print(f"Erro ao tentar clicar em Avançar: {e}")


def _fill_caption(page, caption: str) -> None:
    """Preenche a legenda do Reel."""
    textbox_selectors = [
        "div[contenteditable='true'][aria-label*='Descreva']",
        "div[contenteditable='true'][aria-label*='Describe']",
        "div[contenteditable='true'][aria-label*='pensando']",
        "div[role='textbox'][contenteditable='true']",
    ]

    textbox = None
    deadline = time_module.monotonic() + 15
    while time_module.monotonic() < deadline:
        for sel in textbox_selectors:
            loc = page.locator(sel)
            try:
                for i in range(loc.count()):
                    nth = loc.nth(i)
                    if nth.is_visible():
                        textbox = nth
                        break
            except Exception:
                continue
            if textbox:
                break
        if textbox:
            break
        page.wait_for_timeout(1000)

    if not textbox:
        raise RuntimeError("Nao foi possivel encontrar o campo de texto de legenda do Reel.")

    try:
        textbox.click(force=True)
        page.wait_for_timeout(500)
        page.keyboard.type(caption, delay=10)
    except Exception as e:
        print(f"Aviso ao digitar legenda: {e}")
        
    print(f"Legenda preenchida ({len(caption)} chars).")


def _attach_video(page, video_file: Path) -> None:
    """Anexa o video usando input[type=file] oculto ou file chooser."""
    injected = False
    try:
        file_inputs = page.locator("input[type='file'][accept*='video']")
        if file_inputs.count() > 0:
            file_inputs.first.set_input_files(str(video_file))
            injected = True
            print("Video injetado via input[type=file] (accept=video).")
        else:
            all_file_inputs = page.locator("input[type='file']")
            count = all_file_inputs.count()
            if count > 0:
                for i in range(count - 1, -1, -1):
                    try:
                        all_file_inputs.nth(i).set_input_files(str(video_file))
                        injected = True
                        print(f"Video injetado via input[type=file] index {i}.")
                        break
                    except Exception:
                        continue
    except Exception as e:
        print(f"Falha ao injetar via input[type=file]: {e}")

    if not injected:
        print("Tentando injecao via JavaScript...")
        try:
            page.evaluate('''(filePath) => {
                const inputs = document.querySelectorAll('input[type="file"]');
                if (inputs.length > 0) {
                    const lastInput = inputs[inputs.length - 1];
                    lastInput.style.display = 'block';
                    lastInput.style.opacity = '1';
                    lastInput.style.position = 'fixed';
                    lastInput.style.top = '0';
                    lastInput.style.left = '0';
                    lastInput.style.zIndex = '999999';
                }
            }''')
            page.wait_for_timeout(1000)

            all_file_inputs = page.locator("input[type='file']")
            if all_file_inputs.count() > 0:
                all_file_inputs.last.set_input_files(str(video_file))
                injected = True
                print("Video injetado apos tornar input visivel.")
        except Exception as e:
            print(f"Falha na injecao via JS: {e}")

    if not injected:
        raise RuntimeError("Nao foi possivel anexar o video ao Facebook por nenhum metodo.")


def _click_publish(page) -> None:
    """Clica no botao 'Postar' / 'Publish'."""
    try:
        page.evaluate('''() => {
            const buttons = document.querySelectorAll('div[role="button"]');
            for (const btn of buttons) {
                const txt = (btn.innerText || '').trim();
                if (txt === 'Postar' || txt === 'Publish') {
                    btn.click();
                    return;
                }
            }
        }''')
        print("Botao Postar clicado via JS.")
    except Exception as e:
        print(f"Erro ao tentar clicar em Postar: {e}")


def _wait_for_upload_complete(page) -> None:
    """Aguarda sucesso verificando a saida do /reels/create ou mudancas na URL."""
    deadline = time_module.monotonic() + 180  # 3 minutos max

    while time_module.monotonic() < deadline:
        page.wait_for_timeout(3000)

        # O Facebook geralmente redireciona a pagina ou exibe um toast de confirmacao
        if "reels/create" not in page.url:
            print("Redirecionamento detectado! Post provavelmente concluido.")
            _save_debug_screenshot(page, "fb_success")
            page.wait_for_timeout(5000)
            return

        try:
            # Verifica toasts de sucesso
            success_texts = ["publicado", "posted", "seu reel", "your reel", "compartilhado"]
            for txt in success_texts:
                toast = page.locator(f"div:has-text('{txt}')")
                if toast.count() > 0:
                    print(f"Confirmacao detectada: '{txt}'")
                    _save_debug_screenshot(page, "fb_success_toast")
                    page.wait_for_timeout(3000)
                    return
        except Exception:
            pass

    print("Tempo limite atingido (3 min). O reel pode nao ter sido enviado.")
    _save_debug_screenshot(page, "fb_timeout")
    page.wait_for_timeout(3000)


def _set_audience_to_public(page) -> None:
    """Abre o seletor de publico, escolhe 'Publico' e clica em Salvar/Concluir."""
    try:
        # 1. Clicar no botao atual (Amigos, Somente eu, etc) para abrir o modal
        page.evaluate('''() => {
            const spans = document.querySelectorAll('span, div[role="button"]');
            for (const el of spans) {
                const txt = (el.innerText || '').trim();
                if (txt === 'Amigos' || txt === 'Somente eu' || txt === 'Amigos próximos' || txt === 'Público') {
                    const btn = el.closest('[role="button"]') || el;
                    btn.click();
                    return;
                }
            }
        }''')
        page.wait_for_timeout(2000)

        # 2. Clicar na opcao 'Público'
        page.evaluate('''() => {
            const spans = document.querySelectorAll('span, div');
            for (const el of spans) {
                if ((el.innerText || '').trim() === 'Público' || (el.innerText || '').trim() === 'Public') {
                    const btn = el.closest('[role="button"]') || el;
                    btn.click();
                    break;
                }
            }
        }''')
        page.wait_for_timeout(1000)

        # 3. Clicar em 'Salvar' ou 'Concluir'
        page.evaluate('''() => {
            const btns = document.querySelectorAll('div[role="button"]');
            for (const btn of btns) {
                const txt = (btn.innerText || '').trim();
                if (txt === 'Salvar' || txt === 'Save' || txt === 'Concluir' || txt === 'Done') {
                    btn.click();
                    return;
                }
            }
        }''')
        page.wait_for_timeout(2000)
    except Exception as e:
        print(f"Erro ao tentar configurar publico para Publico: {e}")


