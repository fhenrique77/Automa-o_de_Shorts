#!/bin/bash
# =============================================================
#  Inicia display virtual + noVNC para login manual
#  Use apenas na primeira vez ou quando precisar relogar
# =============================================================
set -e

DISPLAY_NUM=99
RESOLUTION="1280x720x24"
VNC_PORT=5999
NOVNC_PORT=6080

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "🖥️  Iniciando display virtual..."
# Mata instâncias anteriores
pkill -f "Xvfb :$DISPLAY_NUM" 2>/dev/null || true
pkill -f "x11vnc.*:$DISPLAY_NUM" 2>/dev/null || true
pkill -f "websockify.*$NOVNC_PORT" 2>/dev/null || true
sleep 1

# Inicia Xvfb (tela virtual)
Xvfb :$DISPLAY_NUM -screen 0 $RESOLUTION &
sleep 2

# Inicia x11vnc (compartilha a tela virtual)
x11vnc -display :$DISPLAY_NUM -nopw -forever -shared -rfbport $VNC_PORT &
sleep 1

# Inicia noVNC (acesso via navegador web)
NOVNC_DIR=""
for dir in /usr/share/novnc /usr/share/javascript/novnc /snap/novnc/current/utils; do
    if [ -d "$dir" ]; then
        NOVNC_DIR="$dir"
        break
    fi
done
if [ -z "$NOVNC_DIR" ]; then
    NOVNC_DIR="/usr/share/novnc"
fi
websockify --web "$NOVNC_DIR" $NOVNC_PORT localhost:$VNC_PORT &
sleep 1

export DISPLAY=:$DISPLAY_NUM

# Pega o IP público da VPS
VPS_IP=$(curl -s ifconfig.me 2>/dev/null || echo "SEU_IP")

echo ""
echo "=========================================="
echo "  ✅ noVNC iniciado com sucesso!"
echo "=========================================="
echo ""
echo "  Acesse no navegador: http://$VPS_IP:$NOVNC_PORT/vnc.html"
echo ""
echo "  === LOGIN NO YOUTUBE STUDIO ==="
echo "  Em outro terminal SSH, rode:"
echo "    cd $PROJECT_DIR"
echo "    DISPLAY=:$DISPLAY_NUM .venv/bin/python -c \\"
echo "    \"from playwright.sync_api import sync_playwright"
echo "    p = sync_playwright().start()"
echo "    b = p.chromium.launch_persistent_context('browser_data', headless=False)"
echo "    page = b.new_page()"
echo "    page.goto('https://studio.youtube.com')"
echo "    input('Faca login no YouTube e pressione Enter...')"
echo "    b.close(); p.stop()\""
echo ""
echo "  === LOGIN NO TIKTOK ==="
echo "  Em outro terminal SSH, rode:"
echo "    cd $PROJECT_DIR"
echo "    DISPLAY=:$DISPLAY_NUM .venv/bin/python -c \\"
echo "    \"from playwright.sync_api import sync_playwright"
echo "    p = sync_playwright().start()"
echo "    b = p.chromium.launch_persistent_context('browser_data_tiktok', headless=False)"
echo "    page = b.new_page()"
echo "    page.goto('https://www.tiktok.com/tiktokstudio/upload')"
echo "    input('Faca login no TikTok e pressione Enter...')"
echo "    b.close(); p.stop()\""
echo ""
echo "  Após o login, feche com: bash deploy/parar_login.sh"
echo ""
