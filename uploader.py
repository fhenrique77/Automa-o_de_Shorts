from __future__ import annotations

import time as time_module
from pathlib import Path
from typing import Sequence

from config import BASE_DIR, RETRY_ATTEMPTS, RETRY_DELAY_SECONDS

YOUTUBE_STUDIO_URL = "https://studio.youtube.com/"
USER_DATA_DIR = BASE_DIR / "browser_data"


def upload_videos(
    videos: Sequence[dict[str, object]],
    privacy_status: str = "public",
    category_id: str = "22",
) -> list[str]:
    """
    Faz upload em lote para o YouTube Studio usando uma única sessão persistente.
    A primeira execução exigira login manual.
    """
    try:
        from playwright.sync_api import TimeoutError, sync_playwright
    except ImportError:
        raise ImportError(
            "O pacote 'playwright' nao esta instalado. Execute: pip install playwright && playwright install chromium"
        )

    if not videos:
        return []

    print("Iniciando automacao em lote do YouTube Studio...")
    uploaded_refs: list[str] = []
    failed_refs: list[str] = []
    attempts = max(1, int(RETRY_ATTEMPTS))
    delay_seconds = max(0.0, float(RETRY_DELAY_SECONDS))

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            locale="pt-BR",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--mute-audio",
                "--disable-session-crashed-bubble",
                "--hide-crash-restore-bubble",
                "--no-default-browser-check",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--window-position=20000,20000",
            ],
        )

        try:
            page = context.new_page()
            try:
                _open_studio_home(page)
                _ensure_logged_in(page, TimeoutError)
                _dismiss_welcome_modal(page)
            except Exception as e:
                DEBUG_SCREENSHOTS_DIR = BASE_DIR / "debug_screenshots"
                DEBUG_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
                screenshot_path = DEBUG_SCREENSHOTS_DIR / "youtube_init_error.png"
                try:
                    page.screenshot(path=str(screenshot_path))
                    print(f"📸 Screenshot de depuração do YouTube salvo em: {screenshot_path}")
                except Exception as sc_err:
                    print(f"Não foi possível salvar o screenshot de erro do YouTube: {sc_err}")
                print(f"URL atual do YouTube no momento da falha: {page.url}")
                raise e

            for index, video in enumerate(videos, start=1):
                video_path = Path(str(video["video_path"])).resolve()
                if not video_path.exists():
                    raise FileNotFoundError(f"Video nao encontrado em {video_path}")

                title = str(video["title"])
                description = str(video["description"])
                tags = [str(tag).strip() for tag in video.get("tags", []) if str(tag).strip()]

                print(f"Enviando Short {index}/{len(videos)}: {title}...")
                video_uploaded = False
                last_error: Exception | None = None

                for attempt in range(1, attempts + 1):
                    try:
                        _upload_single_video(
                            page=page,
                            video_file=video_path,
                            title=title,
                            description=description,
                            tags=tags,
                            privacy_status=privacy_status,
                            category_id=category_id,
                        )
                        uploaded_refs.append(title)
                        video_uploaded = True
                        break
                    except Exception as exc:
                        last_error = exc
                        # Salvar screenshot do erro no upload
                        DEBUG_SCREENSHOTS_DIR = BASE_DIR / "debug_screenshots"
                        DEBUG_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
                        sc_path = DEBUG_SCREENSHOTS_DIR / f"youtube_upload_error_attempt_{attempt}.png"
                        try:
                            page.screenshot(path=str(sc_path))
                            print(f"📸 Screenshot de depuracao do erro no YouTube salvo em: {sc_path}")
                        except Exception as sc_err:
                            print(f"Nao foi possivel salvar o screenshot de erro do YouTube: {sc_err}")
                        
                        if attempt >= attempts:
                            break
                        print(
                            f"Falha ao enviar '{title}' na tentativa {attempt}/{attempts}: {exc}"
                        )
                        if delay_seconds:
                            print(f"Tentando novamente em {delay_seconds:.0f} segundos...")
                            time_module.sleep(delay_seconds)
                        try:
                            _open_studio_home(page)
                            _dismiss_welcome_modal(page)
                        except Exception:
                            pass

                if not video_uploaded:
                    failed_refs.append(title)
                    print(f"Nao foi possivel enviar '{title}' apos {attempts} tentativa(s).")

                if index < len(videos):
                    print("Preparando o proximo Short...")
                    _open_studio_home(page)
                    _dismiss_welcome_modal(page)
        finally:
            print("Fechando navegador automaticamente...")
            context.close()

    if failed_refs:
        print(f"{len(failed_refs)} Short(s) falharam mesmo apos reprocessamento automatico.")

    return uploaded_refs


def upload_video(
    video_path: str | Path,
    title: str,
    description: str,
    tags: Sequence[str],
    privacy_status: str = "public",
    category_id: str = "22",
) -> str:
    uploaded_refs = upload_videos(
        [
            {
                "video_path": video_path,
                "title": title,
                "description": description,
                "tags": list(tags),
            }
        ],
        privacy_status=privacy_status,
        category_id=category_id,
    )
    return uploaded_refs[0] if uploaded_refs else "UPLOAD_AUTOMATICO_PLAYWRIGHT"


def _open_studio_home(page) -> None:
    page.goto(YOUTUBE_STUDIO_URL)
    _wait_for_studio_header(page)


def _wait_for_studio_header(page) -> None:
    page.wait_for_selector("ytcp-header", timeout=30000)


def _ensure_logged_in(page, timeout_error) -> None:
    try:
        _wait_for_studio_header(page)
        print("Login detectado!")
    except timeout_error:
        print("\n*** LOGIN NECESSARIO ***")
        print("Por favor, faca login na janela do navegador que se abriu.")
        print("O script vai aguardar ate que o painel do Studio seja carregado...")
        page.wait_for_selector("ytcp-header", timeout=0)
        print("Login concluido com sucesso!")


def _dismiss_welcome_modal(page) -> None:
    print("Verificando janela modal de novos canais...")
    try:
        btn_continuar = page.get_by_role("button", name="Continuar")
        if btn_continuar.is_visible(timeout=5000):
            print("Fechando modal de boas vindas...")
            btn_continuar.click()
            page.wait_for_timeout(2000)
    except Exception:
        pass



def _dismiss_auth_dialog(page) -> None:
    """Detecta e remove o modal 'Confirme sua identidade' do YouTube Studio.
    Esse modal (ytcp-auth-confirmation-dialog) aparece como um overlay que
    bloqueia cliques no formulario de upload. Removemos via JS para liberar."""
    try:
        # Executamos a remocao diretamente via JavaScript de forma incondicional e rapida
        page.evaluate("""
            () => {
                const dialogs = document.querySelectorAll('ytcp-auth-confirmation-dialog');
                if (dialogs.length > 0) {
                    console.log("⚠️ Removendo modal de confirmacao de identidade...");
                    dialogs.forEach(el => el.remove());
                    document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(el => el.remove());
                    document.querySelectorAll('.opened[style*="z-index"]').forEach(el => el.remove());
                    // Destrava pointer-events se o dialog os travou
                    document.body.style.pointerEvents = 'auto';
                    document.documentElement.style.pointerEvents = 'auto';
                }
            }
        """)
    except Exception as e:
        print(f"Erro ao remover modal de confirmacao: {e}")


def _sanitize_title(title: str, limit: int = 100) -> str:
    """Limpa e trunca o titulo para caber no YouTube (max 100 chars)."""
    # Remove caracteres problematicos que o YouTube rejeita
    cleaned = title.replace(">>", "").replace("<<", "")
    cleaned = cleaned.strip()
    # Remove espacos duplicados
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip()
        if " " in cleaned:
            cleaned = cleaned.rsplit(" ", 1)[0]
        cleaned = cleaned.rstrip(" ,;:-")
    return cleaned


def _upload_single_video(
    page,
    video_file: Path,
    title: str,
    description: str,
    tags: Sequence[str],
    privacy_status: str,
    category_id: str,
) -> None:
    print("Iniciando upload...")
    try:
        page.locator("#upload-icon").click(timeout=10000)
    except Exception:
        page.get_by_text("Enviar vídeos").click()

    with page.expect_file_chooser() as fc_info:
        page.locator("ytcp-button#select-files-button").click()
    fc_info.value.set_files(str(video_file))

    # Aguarda o formulario de detalhes carregar
    page.wait_for_timeout(5000)

    # --- Sanitizar titulo (max 100 chars, sem >> ) ---
    clean_title = _sanitize_title(title)
    print(f"Titulo sanitizado ({len(clean_title)} chars): {clean_title}")

    # --- Preencher TITULO ---
    # YouTube Studio usa #title-textarea como container do titulo
    print("Preenchendo titulo...")
    title_filled = False
    title_selectors = [
        "#title-textarea #textbox",
        "ytcp-video-title #textbox",
        "#title-textarea div[contenteditable]",
    ]
    for sel in title_selectors:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=5000)
            _dismiss_auth_dialog(page)
            el.click(force=True)
            page.keyboard.press("Control+a")
            page.keyboard.press("Backspace")
            page.wait_for_timeout(300)
            page.keyboard.insert_text(clean_title)
            title_filled = True
            print(f"Titulo preenchido via seletor: {sel}")
            break
        except Exception:
            continue

    if not title_filled:
        # Fallback absoluto: primeiro #textbox na pagina
        print("Usando fallback nth(0) para titulo...")
        _dismiss_auth_dialog(page)
        page.locator("#textbox").nth(0).click(force=True)
        page.keyboard.press("Control+a")
        page.keyboard.press("Backspace")
        page.wait_for_timeout(300)
        page.keyboard.insert_text(clean_title)

    page.wait_for_timeout(1000)

    # --- Preencher DESCRICAO ---
    print("Preenchendo descricao...")
    full_description = description
    if tags:
        full_description += f"\n\n{' '.join(tags)}"
    full_description = full_description.replace(">>", "").replace("<<", "")
    print(f"Descricao ({len(full_description)} chars)")

    desc_filled = False
    desc_selectors = [
        "#description-textarea #textbox",
        "ytcp-video-description #textbox",
        "#description-textarea div[contenteditable]",
    ]
    for sel in desc_selectors:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=5000)
            _dismiss_auth_dialog(page)
            el.click(force=True)
            page.keyboard.press("Control+a")
            page.keyboard.press("Backspace")
            page.wait_for_timeout(300)
            page.keyboard.insert_text(full_description)
            desc_filled = True
            print(f"Descricao preenchida via seletor: {sel}")
            break
        except Exception:
            continue

    if not desc_filled:
        # Fallback absoluto: segundo #textbox na pagina
        print("Usando fallback nth(1) para descricao...")
        _dismiss_auth_dialog(page)
        page.locator("#textbox").nth(1).click(force=True)
        page.keyboard.press("Control+a")
        page.keyboard.press("Backspace")
        page.wait_for_timeout(300)
        page.keyboard.insert_text(full_description)

    page.wait_for_timeout(1000)

    # Remover modal de autenticacao se presente antes de interagir com o formulario
    _dismiss_auth_dialog(page)

    page.locator("tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']").click(timeout=15000, force=True)

    next_button = page.locator("ytcp-button#next-button")
    for _ in range(3):
        _dismiss_auth_dialog(page)
        next_button.wait_for(state="attached", timeout=300000)
        next_button.dispatch_event("click")
        page.wait_for_timeout(2000)

    print("Aguardando etapa de visibilidade...")
    _dismiss_auth_dialog(page)
    visibility_timeout_ms = 300000
    visibility_button = page.locator(f"tp-yt-paper-radio-button[name='{privacy_status.upper()}']")
    visibility_button.wait_for(state="visible", timeout=visibility_timeout_ms)

    _dismiss_auth_dialog(page)
    if privacy_status.lower() == "public":
        visibility_button.click(timeout=10000, force=True)
    else:
        page.locator("tp-yt-paper-radio-button[name='PRIVATE']").click(timeout=10000, force=True)

    print("Publicando video...")
    page.locator("ytcp-button#done-button").dispatch_event("click")

    print("Aguardando confirmacao do YouTube...")
    title_marker = clean_title[:35].strip() or clean_title
    try:
        page.wait_for_function(
            """(marker) => (document.body ? document.body.innerText : '').includes(marker)""",
            title_marker,
            timeout=60000,
        )
    except Exception:
        pass

    page.wait_for_function(
        r"""() => !/Envio em\s*\d+%/i.test(document.body ? document.body.innerText : '')""",
        timeout=1800000,
    )
    print("Upload concluido com sucesso via automacao!")
    page.wait_for_timeout(2000)
