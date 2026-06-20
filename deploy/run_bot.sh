#!/bin/bash
# =============================================================
#  Wrapper para rodar o bot com display virtual (Xvfb)
#  Usado pelo cron — inclui flock para evitar concorrência
# =============================================================

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
LOCK_FILE="$PROJECT_DIR/.bot.lock"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d_%H%M).log"

mkdir -p "$LOG_DIR"

# flock evita que duas execuções rodem ao mesmo tempo
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Bot ja esta em execucao. Abortando." >> "$LOG_FILE"
    exit 0
fi

echo "=== Execucao iniciada em $(date) ===" >> "$LOG_FILE" 2>&1

# Roda o bot dentro de xvfb-run (cria e destroi display automaticamente)
xvfb-run --auto-servernum --server-args="-screen 0 1280x720x24" \
    "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/main.py" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "=== Execucao finalizada em $(date) com codigo $EXIT_CODE ===" >> "$LOG_FILE" 2>&1

# Limpa logs antigos (mantém últimos 30 dias)
find "$LOG_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true

# Libera o lock
flock -u 200

exit $EXIT_CODE
