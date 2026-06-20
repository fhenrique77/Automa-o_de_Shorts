#!/bin/bash
# =============================================================
#  Setup automático para VPS Ubuntu — Oracle Cloud Free Tier
#  ARM64 (A1.Flex) ou x86_64 (Micro)
# =============================================================
set -e

echo "=========================================="
echo "  🚀 Setup do Podcast Automation Bot"
echo "=========================================="

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# 1. Atualizar sistema e configurar timezone
echo ""
echo "[1/7] Atualizando sistema e configurando timezone..."
sudo apt-get update -qq
sudo apt-get upgrade -y -qq
sudo timedatectl set-timezone America/Sao_Paulo

# 2. Instalar dependências do sistema
echo "[2/7] Instalando dependencias do sistema..."
sudo apt-get install -y -qq \
    python3 python3-pip python3-venv \
    ffmpeg \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    fonts-liberation fonts-noto-color-emoji \
    libnss3 libatk-bridge2.0-0 libdrm2 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2t64 libatspi2.0-0 libxshmfence1 \
    curl wget git

# Instalar Node.js (necessário para yt-dlp JS challenge solving)
if ! command -v node &> /dev/null; then
    echo "  Instalando Node.js..."
    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - 2>/dev/null
    sudo apt-get install -y -qq nodejs 2>/dev/null || true
fi

# 3. Criar ambiente virtual Python
echo "[3/7] Criando ambiente virtual Python..."
if [ ! -d "$PROJECT_DIR/.venv" ]; then
    python3 -m venv "$PROJECT_DIR/.venv"
fi
source "$PROJECT_DIR/.venv/bin/activate"

# 4. Instalar dependências Python
echo "[4/7] Instalando dependencias Python..."
pip install --upgrade pip -q
pip install -q \
    yt-dlp \
    youtube-transcript-api \
    imageio-ffmpeg \
    playwright \
    google-genai

# 5. Instalar navegador Playwright
echo "[5/7] Instalando Chromium via Playwright..."
python3 -m playwright install chromium
python3 -m playwright install-deps chromium

# 6. Criar diretórios necessários
echo "[6/7] Criando diretorios..."
mkdir -p "$PROJECT_DIR/logs"
mkdir -p "$PROJECT_DIR/temp_videos"
mkdir -p "$PROJECT_DIR/temp_clips"
mkdir -p "$PROJECT_DIR/browser_data"
mkdir -p "$PROJECT_DIR/browser_data_tiktok"

# 7. Copiar config VPS se não existir config personalizado
echo "[7/7] Verificando configuracoes..."
if [ -f "$PROJECT_DIR/config_vps.py" ] && [ ! -f "$PROJECT_DIR/.config_applied" ]; then
    echo "  Aplicando config_vps.py (Whisper desativado, preset otimizado)..."
    cp "$PROJECT_DIR/config.py" "$PROJECT_DIR/config_original.py"
    cp "$PROJECT_DIR/config_vps.py" "$PROJECT_DIR/config.py"
    touch "$PROJECT_DIR/.config_applied"
fi

# Configurar firewall (liberar porta noVNC temporariamente)
sudo iptables -I INPUT -p tcp --dport 6080 -j ACCEPT 2>/dev/null || true

echo ""
echo "=========================================="
echo "  ✅ Instalacao concluida com sucesso!"
echo "=========================================="
echo ""
echo "Proximo passo:"
echo "  1. Rode: bash deploy/iniciar_login.sh"
echo "  2. Acesse: http://SEU_IP:6080/vnc.html"
echo "  3. Faca login no YouTube e TikTok"
echo "  4. Rode: bash deploy/parar_login.sh"
echo "  5. Rode: bash deploy/cron_setup.sh"
echo ""
