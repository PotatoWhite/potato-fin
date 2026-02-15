#!/bin/bash
# 주가 업데이트 래퍼 스크립트 (launchd에서 호출)
# 주말이면 건너뛰고, venv Python으로 실행, 로그 기록

set -euo pipefail

STOCK_DIR="/home/bravopotato/Spaces/finspace/potato-fin"
PYTHON="$STOCK_DIR/.venv/bin/python3"
SCRIPT="$STOCK_DIR/주가_업데이트.py"
LOG_DIR="$HOME/logs/stock-monitor"

mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/update_$(date +%Y%m%d_%H%M%S).log"


echo "$(date): 주가 업데이트 시작" >> "$LOG_FILE"

cd "$STOCK_DIR"
"$PYTHON" "$SCRIPT" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "$(date): 완료 (exit=$EXIT_CODE)" >> "$LOG_FILE"

# 30일 이상 된 로그 삭제
find "$LOG_DIR" -name "update_*.log" -mtime +30 -delete 2>/dev/null || true

exit $EXIT_CODE
