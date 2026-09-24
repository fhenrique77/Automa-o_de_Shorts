from playwright.sync_api import sync_playwright
from config import TIKTOK_USER_DATA_DIR, TIKTOK_UPLOAD_URL

print("\n=======================================================")
print("[LOGIN] INICIAL NO TIKTOK — Conta @trechosbr552")
print("=======================================================")
print("Uma janela do navegador vai abrir agora.")
print("1. Faca login com sua conta Google")
print("2. Quando ver a pagina de upload do TikTok, feche a janela do navegador")
print("=======================================================\n")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        channel="chrome",
        user_data_dir=str(TIKTOK_USER_DATA_DIR),
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-notifications",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
            "--no-default-browser-check",
            "--disable-gpu",
            "--disable-dev-shm-usage",
        ],
        locale="pt-BR",
    )
    page = context.new_page()
    page.goto(TIKTOK_UPLOAD_URL)
    
    print("Aguardando voce fazer login e fechar a janela...")
    try:
        page.wait_for_event("close", timeout=0)
    except Exception:
        pass
    print("\n[OK] Sessao do TikTok (@trechosbr552) salva com sucesso!")
