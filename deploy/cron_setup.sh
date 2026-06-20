#!/bin/bash
# =============================================================
#  Configura cron para rodar o bot nos horários otimizados
#  Horários: 12:45, 15:15, 17:45, 20:15 (horário de Brasília)
#
#  A VPS está configurada com timezone America/Sao_Paulo
#  então os horários do cron já são BRT.
# =============================================================
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WRAPPER="$PROJECT_DIR/deploy/run_bot.sh"

if [ ! -f "$WRAPPER" ]; then
    echo "❌ Erro: $WRAPPER nao encontrado!"
    echo "   Rode 'bash deploy/setup_vps.sh' primeiro."
    exit 1
fi

chmod +x "$WRAPPER"

# Remove crontab anterior do projeto
crontab -l 2>/dev/null | grep -v "podcast_automation" | crontab - 2>/dev/null || true

# Adiciona novos horários (BRT — timezone da VPS)
(crontab -l 2>/dev/null; cat <<CRON
# === Podcast Automation Bot ===
45 12 * * * $WRAPPER  # podcast_automation 12:45
15 15 * * * $WRAPPER  # podcast_automation 15:15
45 17 * * * $WRAPPER  # podcast_automation 17:45
15 20 * * * $WRAPPER  # podcast_automation 20:15
CRON
) | crontab -

echo ""
echo "=========================================="
echo "  ✅ Cron configurado com sucesso!"
echo "=========================================="
echo ""
echo "  Horários de postagem (Horario de Brasilia):"
echo "    📌 12:45 — Captura pico do almoço"
echo "    📌 15:15 — Janela vespertina TikTok"
echo "    📌 17:45 — Pré-pico noturno"
echo "    📌 20:15 — Zona dourada noturna"
echo ""
echo "  Logs salvos em: $PROJECT_DIR/logs/"
echo "  Ver tarefas: crontab -l"
echo "  Ver último log: ls -t $PROJECT_DIR/logs/*.log | head -1 | xargs tail -50"
echo ""
