from playwright.sync_api import sync_playwright
from config import INSTAGRAM_USER_DATA_DIR, INSTAGRAM_URL

print("\n=======================================================")
print("🔑 LOGIN INICIAL NO INSTAGRAM")
print("=======================================================")
print("Uma janela do navegador vai abrir agora.")
print("1. Faça login com sua conta do Instagram")
print("2. Quando ver a pagina inicial do Instagram, feche a janela do navegador")
print("=======================================================\n")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(INSTAGRAM_USER_DATA_DIR),
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
            "--no-default-browser-check",
            "--disable-gpu",
            "--disable-dev-shm-usage",
        ],
        locale="pt-BR",
    )
    page = context.new_page()
    page.goto(INSTAGRAM_URL)
    
    print("Aguardando voce fazer login e fechar a janela...")
    try:
        page.wait_for_event("close", timeout=0)
    except Exception:
        pass
    print("\n✅ Sessão do Instagram salva com sucesso!")
