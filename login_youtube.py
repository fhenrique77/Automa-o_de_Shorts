from playwright.sync_api import sync_playwright
from config import BASE_DIR

USER_DATA_DIR = BASE_DIR / "browser_data"
YOUTUBE_STUDIO_URL = "https://studio.youtube.com/"

print("\n=======================================================")
print("  LOGIN INICIAL NO YOUTUBE STUDIO")
print("=======================================================")
print("Uma janela do navegador vai abrir agora.")
print("1. Faca login com sua conta do canal do YouTube")
print("2. Quando ver a pagina inicial do YouTube Studio, feche a janela do navegador")
print("=======================================================\n")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(USER_DATA_DIR),
        headless=False,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        locale="pt-BR",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
            "--no-default-browser-check",
            "--disable-gpu",
            "--disable-dev-shm-usage",
        ],
    )
    page = context.new_page()
    page.goto(YOUTUBE_STUDIO_URL)
    
    print("Aguardando voce fazer login e fechar a janela...")
    try:
        page.wait_for_event("close", timeout=0)
    except Exception:
        pass
    print("\n  Sessao do YouTube Studio salva com sucesso!")
