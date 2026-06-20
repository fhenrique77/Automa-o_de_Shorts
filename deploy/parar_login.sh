#!/bin/bash
# =============================================================
#  Para o noVNC e display virtual (usar após o login)
# =============================================================

echo "🛑 Parando noVNC e display virtual..."

pkill -f "websockify" 2>/dev/null || true
pkill -f "x11vnc" 2>/dev/null || true
pkill -f "Xvfb :99" 2>/dev/null || true

# Fecha porta do firewall por segurança
sudo iptables -D INPUT -p tcp --dport 6080 -j ACCEPT 2>/dev/null || true

echo "✅ Tudo parado. O bot vai rodar via cron sem VNC."
