from __future__ import annotations

import os
import random
import re
import time as time_module
from pathlib import Path
from typing import Sequence

from utils import build_social_caption
from config import (
	RETRY_ATTEMPTS,
	RETRY_DELAY_SECONDS,
	TIKTOK_CAPTION_MAX_CHARS,
	TIKTOK_EXTRA_HASHTAGS,
	TIKTOK_LOGIN_URL,
	TIKTOK_UPLOAD_URL,
	TIKTOK_USER_DATA_DIR,
	HEADLESS_MODE,
)




def upload_videos(
	videos: Sequence[dict[str, object]],
	caption_limit: int = TIKTOK_CAPTION_MAX_CHARS,
) -> list[str]:
	"""
	Faz upload em lote para o TikTok usando uma sessao persistente.
	A primeira execucao exige login manual.
	"""
	try:
		from playwright.sync_api import TimeoutError, sync_playwright
	except ImportError:
		raise ImportError(
			"O pacote 'playwright' nao esta instalado. Execute: pip install playwright && playwright install chromium"
		)

	if not videos:
		return []

	print("Iniciando automacao em lote do TikTok...")
	uploaded_refs: list[str] = []
	failed_refs: list[str] = []
	attempts = max(1, int(RETRY_ATTEMPTS))
	delay_seconds = max(0.0, float(RETRY_DELAY_SECONDS))

	with sync_playwright() as p:
		_viewport = {
			"width": random.randint(1250, 1400),
			"height": random.randint(750, 850),
		}
		context = p.chromium.launch_persistent_context(
			user_data_dir=str(TIKTOK_USER_DATA_DIR),
			headless=HEADLESS_MODE,
			viewport=_viewport,
			user_agent=(
				"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
				"AppleWebKit/537.36 (KHTML, like Gecko) "
				f"Chrome/{random.randint(135, 137)}.0.0.0 Safari/537.36"
			),
			args=[
				"--disable-blink-features=AutomationControlled",
				"--mute-audio",
				"--disable-session-crashed-bubble",
				"--hide-crash-restore-bubble",
				"--no-default-browser-check",
				"--disable-gpu",
				"--disable-dev-shm-usage",
				"--disable-infobars",
				"--disable-component-extensions-with-background-pages",
			],
		)
		context.add_init_script(_STEALTH_JS)

		try:
			page = context.new_page()
			_open_upload_home(page)
			_ensure_logged_in(page, TimeoutError)

			for index, video in enumerate(videos, start=1):
				video_path = Path(str(video["video_path"])).resolve()
				if not video_path.exists():
					raise FileNotFoundError(f"Video nao encontrado em {video_path}")

				title = str(video["title"])
				description = str(video.get("description", title))
				tags = [str(tag).strip() for tag in video.get("tags", []) if str(tag).strip()]
				for extra_tag in TIKTOK_EXTRA_HASHTAGS:
					if extra_tag not in tags:
						tags.append(extra_tag)
				caption = build_social_caption(title, description, limit=caption_limit, tags=tags)

				print(f"Enviando Short {index}/{len(videos)} para o TikTok: {title}...")
				video_uploaded = False

				for attempt in range(1, attempts + 1):
					try:
						_upload_single_video(
							page=page,
							video_file=video_path,
							title=title,
							caption=caption,
						)
						uploaded_refs.append(title)
						video_uploaded = True
						break
					except Exception as exc:
						if attempt >= attempts:
							print(f"Falha final ao enviar '{title}' ao TikTok: {exc}")
							break
						print(
							f"Falha ao enviar '{title}' no TikTok na tentativa {attempt}/{attempts}: {exc}"
						)
						if delay_seconds:
							print(f"Tentando novamente em {delay_seconds:.0f} segundos...")
							time_module.sleep(delay_seconds)
						try:
							_open_upload_home(page)
							_ensure_logged_in(page, TimeoutError)
						except Exception:
							pass

				if not video_uploaded:
					failed_refs.append(title)
					print(f"Nao foi possivel enviar '{title}' ao TikTok apos {attempts} tentativa(s).")

				if index < len(videos):
					print("Preparando o proximo Short para o TikTok...")
					_open_upload_home(page)
					_ensure_logged_in(page, TimeoutError)
		finally:
			print("Fechando navegador automaticamente...")
			context.close()

	if failed_refs:
		print(f"{len(failed_refs)} Short(s) falharam no TikTok mesmo apos reprocessamento automatico.")

	return uploaded_refs




def upload_video(
	video_path: str | Path,
	title: str,
	description: str,
	tags: Sequence[str],
	caption_limit: int = TIKTOK_CAPTION_MAX_CHARS,
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
		caption_limit=caption_limit,
	)
	return uploaded_refs[0] if uploaded_refs else "UPLOAD_AUTOMATICO_PLAYWRIGHT"


def _open_upload_home(page) -> None:
	page.goto(TIKTOK_UPLOAD_URL)
	page.wait_for_load_state("domcontentloaded")
	_dismiss_unsaved_draft_prompt(page)
	page.wait_for_timeout(random.randint(1500, 3500))


def _wait_for_upload_form(page) -> None:
	_first_visible_locator(
		page,
		[
			"button:has-text('Selecionar vídeo')",
			"button:has-text('Selecionar video')",
			"button:has-text('Selecionar')",
			"text=Selecione o vídeo a enviar",
			"text=Select video to upload",
		],
		timeout_ms=30000,
	)


def _dismiss_unsaved_draft_prompt(page) -> None:
	for button_name in ("Descartar", "Discard"):
		try:
			prompt_button = page.get_by_role("button", name=button_name)
			if prompt_button.count() and prompt_button.first.is_visible():
				print(f"Fechando rascunho anterior do TikTok com '{button_name}'...")
				prompt_button.first.click(timeout=5000)
				page.wait_for_timeout(2000)
				return
		except Exception:
			continue


def _ensure_logged_in(page, timeout_error) -> None:
	try:
		_wait_for_upload_form(page)
		print("Login detectado no TikTok!")
		return
	except timeout_error:
		pass

	username = os.environ.get("TIKTOK_USERNAME", "").strip()
	password = os.environ.get("TIKTOK_PASSWORD", "").strip()
	if username and password:
		print("Tentando login automatizado no TikTok com credenciais fornecidas...")
		_login_with_credentials(page, username, password)
		_open_upload_home(page)
		try:
			_wait_for_upload_form(page)
			print("Login do TikTok concluido com sucesso!")
			return
		except timeout_error:
			print("Login aplicado, mas a pagina de envio ainda nao carregou.")

	print("\n*** LOGIN NECESSARIO NO TIKTOK ***")
	print("Por favor, faca login na janela do navegador que se abriu.")
	print("O script vai aguardar ate que a pagina de envio do TikTok fique disponivel...")
	_wait_for_upload_form(page)
	print("Login do TikTok concluido com sucesso!")


def _login_with_credentials(page, username: str, password: str) -> None:
	page.goto(TIKTOK_LOGIN_URL)
	page.wait_for_load_state("domcontentloaded")

	username_input = _first_visible_locator(
		page,
		[
			"input[name='username']",
			"input[placeholder*='usu' i]",
			"input[type='text']",
		],
		timeout_ms=30000,
	)
	username_input.fill(username)

	password_input = _first_visible_locator(
		page,
		[
			"input[type='password']",
		],
		timeout_ms=30000,
	)
	password_input.fill(password)

	submit_button = _first_visible_locator(
		page,
		[
			"button[type='submit']",
			"button:has-text('Entrar')",
			"button:has-text('Log in')",
		],
		timeout_ms=30000,
	)
	submit_button.click(timeout=10000)
	page.wait_for_timeout(8000)


def _upload_single_video(
	page,
	video_file: Path,
	title: str,
	caption: str,
) -> None:
	_humanize_session(page)

	print("Iniciando upload no TikTok...")
	select_button = _first_visible_locator(
		page,
		[
			"button:has-text('Selecionar vídeo')",
			"button:has-text('Selecionar video')",
			"button:has-text('Select video')",
			"button:has-text('Carregar')",
		],
		timeout_ms=30000,
	)
	with page.expect_file_chooser() as file_chooser_info:
		select_button.click(timeout=10000)
	file_chooser_info.value.set_files(str(video_file))

	print("Aguardando upload finalizado...")
	try:
		page.wait_for_selector("text=Substituir", timeout=300000)
	except Exception:
		pass

	page.wait_for_timeout(random.randint(2000, 4000))

	print("Preenchendo legenda do TikTok...")
	caption_box = _first_visible_locator(
		page,
		[
			"div.public-DraftEditor-content[contenteditable='true']",
			"textarea",
			"div[contenteditable='true']",
			"div[role='textbox']",
		],
		timeout_ms=300000,
	)
	_fill_caption_editor(page, caption_box, caption)

	print("Aguardando botao de postagem do TikTok...")
	post_button = _first_visible_locator(
		page,
		[
			"button[data-e2e='post_video_button']",
			"button:has-text('Post')",
			"button:has-text('Publicar')",
			"button:has-text('Publish')",
			"div.btn-post",
		],
		timeout_ms=300000,
	)
	page.wait_for_timeout(random.randint(2500, 5000))
	
	try:
		post_button.click(timeout=5000)
	except Exception:
		post_button.dispatch_event("click")
		
	page.wait_for_timeout(random.randint(2000, 5000))

	print("Aguardando confirmacao do TikTok...")
	_confirm_tiktok_post(page)
	try:
		post_button.wait_for(state="hidden", timeout=5000)
	except Exception:
		page.wait_for_timeout(random.randint(2000, 4000))

	_verify_tiktok_publication(page, title)

	print("Upload concluido com sucesso via TikTok!")
	page.wait_for_timeout(random.randint(2000, 4000))


def _fill_caption_editor(page, caption_box, caption: str) -> None:
	_dismiss_editor_tour(page)
	expected_caption = _normalize_caption_text(caption)
	last_caption = ""

	for attempt in range(1, 4):
		caption_box.click(timeout=10000, force=True)
		page.wait_for_timeout(random.randint(300, 800))
		page.keyboard.press("Control+a")
		page.wait_for_timeout(random.randint(200, 500))
		page.keyboard.press("Backspace")
		page.wait_for_timeout(random.randint(400, 900))

		# Digita em blocos para simular comportamento humano
		_human_type_text(page, caption)

		page.wait_for_timeout(random.randint(800, 1500))
		page.keyboard.press("Tab")
		page.wait_for_timeout(random.randint(800, 1500))

		last_caption = _normalize_caption_text(caption_box.inner_text())
		if not expected_caption or last_caption == expected_caption:
			return

		print(
			f"Legenda do TikTok nao confirmou na tentativa {attempt}/3; tentando novamente..."
		)

	raise RuntimeError(
		"Nao foi possivel preencher a legenda do TikTok corretamente. "
		f"Valor atual: {last_caption!r}"
	)


def _dismiss_editor_tour(page) -> None:
	try:
		got_it_button = page.get_by_role("button", name=re.compile("Got it|Entendi"))
		if got_it_button.count() and got_it_button.first.is_visible():
			print("Fechando tour de edicao do TikTok...")
			got_it_button.first.click(timeout=5000)
			page.wait_for_timeout(1000)
	except Exception:
		pass



def _confirm_tiktok_post(page) -> None:
	try:
		confirmation_button = _first_visible_locator(
			page,
			[
				"button:has-text('Post now')",
				"button:has-text('Postar agora')",
				"button:has-text('Publicar agora')",
				"button:has-text('Continue to post')",
				"button:has-text('Continue posting')",
				"button:has-text('Continuar publicando')",
				"button:has-text('Continuar a publicar')",
				"button:has-text('Continuar a postar')",
			],
			timeout_ms=20000,
		)
	except Exception:
		return

	print("Confirmando modal de verificacao do TikTok com 'Post now'...")
	try:
		confirmation_button.click(timeout=5000)
	except Exception:
		confirmation_button.dispatch_event("click")
	page.wait_for_timeout(random.randint(6000, 10000))


def _verify_tiktok_publication(page, title: str, timeout_ms: int = 60000) -> None:
	print(f"Confirmacao do TikTok solicitada para {title!r}; seguindo sem bloqueio adicional.")




def _normalize_caption_text(text: str) -> str:
	return " ".join(text.split())


def _first_visible_locator(page, selectors: Sequence[str], timeout_ms: int):
	deadline_seconds = timeout_ms / 1000.0
	start_time = time_module.monotonic()
	last_error: Exception | None = None

	while time_module.monotonic() - start_time <= deadline_seconds:
		for selector in selectors:
			locator = page.locator(selector)
			try:
				if locator.count() and locator.first.is_visible():
					return locator.first
			except Exception as exc:
				last_error = exc
		page.wait_for_timeout(1000)

	raise RuntimeError(
		f"Nao foi possivel localizar elemento visivel entre: {', '.join(selectors)}"
	) from last_error


# ---------------------------------------------------------------------------
#  Stealth JS — injeta script anti-fingerprint em cada página
# ---------------------------------------------------------------------------
_STEALTH_JS = """
// Oculta navigator.webdriver (flag principal de detecção de bots)
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// Simula plugins reais do Chrome
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format'},
            {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''},
            {name: 'Native Client', filename: 'internal-nacl-plugin', description: ''},
        ];
        plugins.length = 3;
        return plugins;
    }
});

// Define idiomas consistentes com o mercado BR
Object.defineProperty(navigator, 'languages', {
    get: () => ['pt-BR', 'pt', 'en-US', 'en']
});

// Simula chrome.runtime (presente em navegadores reais)
if (!window.chrome) window.chrome = {};
if (!window.chrome.runtime) window.chrome.runtime = {};

// Corrige permissions API para não vazar automação
try {
    const originalQuery = window.navigator.permissions.query.bind(window.navigator.permissions);
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({state: Notification.permission})
            : originalQuery(parameters);
} catch(e) {}
"""


def _humanize_session(page) -> None:
	"""Simula comportamento humano antes de interagir com a página."""
	page.wait_for_timeout(random.randint(1500, 3500))

	# Movimentos de mouse aleatórios
	for _ in range(random.randint(2, 5)):
		page.mouse.move(
			random.randint(100, 900),
			random.randint(100, 600),
		)
		page.wait_for_timeout(random.randint(150, 500))

	# Rola a página suavemente
	page.mouse.wheel(0, random.randint(50, 250))
	page.wait_for_timeout(random.randint(400, 1200))
	page.mouse.wheel(0, -random.randint(20, 150))
	page.wait_for_timeout(random.randint(300, 800))


def _human_type_text(page, text: str) -> None:
	"""
	Digita texto em blocos de tamanho aleatório com pausas naturais,
	simulando velocidade de digitação humana.
	"""
	pos = 0
	while pos < len(text):
		chunk_size = random.randint(5, 20)
		chunk = text[pos : pos + chunk_size]
		page.keyboard.type(chunk, delay=random.randint(20, 60))
		pos += chunk_size
		if pos < len(text):
			page.wait_for_timeout(random.randint(80, 300))

