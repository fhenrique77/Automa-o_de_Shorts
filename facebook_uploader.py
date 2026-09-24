from __future__ import annotations

import time as time_module
import re
from pathlib import Path
from typing import Sequence
from publication import PublicationAttempt, PublicationReceipt, perform_upload
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


def upload_videos(videos: Sequence[dict[str, object]], caption_limit: int = FACEBOOK_CAPTION_MAX_CHARS,
                  *, on_submitting=None, on_confirmed=None) -> list[PublicationReceipt]:
    """Return explicit receipts. Never retry a potentially submitted publication."""
    from playwright.sync_api import TimeoutError, sync_playwright
    if not videos:
        return []
    receipts = []
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
            channel="chrome",
            headless=False,
            args=chromium_args,
            locale="pt-BR",
            viewport={"width": 1280, "height": 900},
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
                _ensure_logged_in(page, TimeoutError)
                caption = build_social_caption(title, description, limit=caption_limit, tags=tags)
                publication = PublicationAttempt(
                    "facebook",
                    (lambda: on_submitting(video)) if on_submitting else None,
                    (lambda receipt: on_confirmed(video, receipt)) if on_confirmed else None,
                )
                receipts.append(perform_upload(lambda: _upload_single_video(page, video_path, caption, publication), publication))
        finally:
            context.close()
    return receipts


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
    except Exception:
        pass

    raise RuntimeError("Sessao do Facebook expirada; execute login_facebook.py novamente.")


def _upload_single_video(page, video_file: Path, caption: str, publication: PublicationAttempt) -> None:
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

    # 4. Clicar Avançar (do step 2 para step 3 - Configurações/Legenda)
    print("Clicando Avançar (2/2)...")
    _click_avancar(page)
    page.wait_for_timeout(4000)
    _save_debug_screenshot(page, "fb_reels_step4_config")

    # 5. Preencher legenda no passo "Compartilhar Reel"
    print("Preenchendo legenda...")
    _fill_caption(page, caption)
    page.wait_for_timeout(2000)
    _save_debug_screenshot(page, "fb_reels_step5_caption")

    # 5.5 Definir publico como "Publico"
    print("Configurando privacidade para Publico...")
    _set_audience_to_public(page)
    _save_debug_screenshot(page, "fb_reels_step5_5_public_set")

    # 6. Publicar
    print("Publicando...")
    _click_publish(page, publication)

    # 7. Aguardar confirmacao
    print("Aguardando upload finalizar...")
    _wait_for_upload_complete(page, publication)

    print("Upload concluido com sucesso via Facebook Reels!")


def _click_avancar(page) -> None:
    """Clica no botão 'Avançar' ou 'Next'."""
    button = page.get_by_role("button", name=re.compile(r"^(Avançar|Next|Seguinte)$", re.I)).first
    button.wait_for(state="visible", timeout=30000)
    button.click(timeout=10000)


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
        try:
            target = page.get_by_text(re.compile(r"Adicione um v[ií]deo|Add a video", re.I)).first
            with page.expect_file_chooser(timeout=10000) as chooser:
                target.click(timeout=10000)
            chooser.value.set_files(str(video_file))
            injected = True
            print("Video anexado pelo seletor de arquivo do Facebook.")
        except Exception as exc:
            print(f"Seletor de arquivo do Facebook indisponivel: {exc}")

    if not injected:
        raise RuntimeError("Nao foi possivel anexar o video ao Facebook por nenhum metodo.")


def _click_publish(page, publication: PublicationAttempt) -> None:
    import re
    button = page.get_by_role("button", name=re.compile(r"^(Postar|Publicar|Publish|Post)$")).last
    button.wait_for(state="visible", timeout=30000)
    publication.before_submit(page)
    button.click(timeout=30000)


def _wait_for_upload_complete(page, publication: PublicationAttempt):
    return publication.confirm(page, timeout_ms=180000)


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


