#!/bin/bash
set -e

# .env 로드
if [ -f /app/.env ]; then
    set -a; source /app/.env; set +a
fi

# 환경변수를 cron에 전달 (cron은 env를 상속받지 않으므로)
printenv | grep -E '^(FINNHUB|TELEGRAM|TELEGRAPH|STOCK_DIR|PYTHON|CLAUDE|LOG_DIR|HOME|PATH|TZ|NODE)' \
    > /etc/environment

# cron 시작
cron

# telegram bot 시작 (foreground — 컨테이너 유지)
exec python3 /app/telegram_bot.py
