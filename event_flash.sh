#!/bin/bash
# 이벤트 플래시 분석 (Tier 2)
# news_monitor.py가 이상 감지 시 자동 트리거
# Claude Haiku로 30초 빠른 분석 → 텔레그램 전송
#
# Usage: event_flash.sh <trigger_file.json>

set -euo pipefail

unset CLAUDECODE 2>/dev/null || true

STOCK_DIR="/home/bravopotato/Spaces/finspace/potato-fin"
PYTHON="$STOCK_DIR/.venv/bin/python3"
CLAUDE="/home/linuxbrew/.linuxbrew/bin/claude"
LOG_DIR="$HOME/logs/stock-monitor"

mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/flash_$(date +%Y%m%d_%H%M%S).log"

TRIGGER_FILE="${1:-}"
if [[ -z "$TRIGGER_FILE" || ! -f "$TRIGGER_FILE" ]]; then
    echo "Error: 트리거 파일 없음: $TRIGGER_FILE" >> "$LOG_FILE"
    exit 1
fi

TRIGGER_DATA=$(cat "$TRIGGER_FILE")
echo "$(date): 이벤트 플래시 시작" >> "$LOG_FILE"
echo "트리거: $TRIGGER_DATA" >> "$LOG_FILE"

# alert_config.json에서 해당 종목 설정 읽기
ALERT_CONFIG=$(cat "$STOCK_DIR/alert_config.json" 2>/dev/null || echo '{}')

# 최신 모니터 데이터
LATEST_DATA=$(cat "$STOCK_DIR/data/monitor/latest.json" 2>/dev/null || echo '{}')

# Claude Haiku로 빠른 분석
FLASH_RESULT=$("$CLAUDE" -p "이벤트 플래시 분석을 수행하라. 30초 이내 빠른 판단.

=== 트리거 데이터 ===
$TRIGGER_DATA

=== 종목 알림 설정 ===
$ALERT_CONFIG

=== 최신 모니터 데이터 ===
$LATEST_DATA

아래 형식으로만 응답하라 (텔레그램 Markdown 형식):

⚡ *이벤트 플래시*

*종목/이벤트*: (종목명 또는 경제지표명)
*원인*: (1줄 — 왜 트리거 됐는지)
*영향*: (1줄 — 포트폴리오에 미치는 영향)
*판정*: (과잉반응/적정반응/과소반응 중 택1, 확률%)
*대응*: (구체적 액션 1개 — 매수/매도/홀드/관망 + 가격 조건)
*손절선*: (해당 시 alert_config.json의 손절선 표기)" \
    --allowedTools "Read" \
    --permission-mode bypassPermissions \
    --model haiku \
    --max-budget-usd 0.50 \
    2>> "$LOG_FILE")

echo "$(date): 분석 완료" >> "$LOG_FILE"
echo "$FLASH_RESULT" >> "$LOG_FILE"

# 텔레그램 전송
set -a
. "$STOCK_DIR/.env"
set +a

API="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"
CHAT_ID="${TELEGRAM_CHAT_ID}"

curl -s -X POST "$API/sendMessage" \
    -d chat_id="$CHAT_ID" \
    -d text="$FLASH_RESULT" \
    -d parse_mode="Markdown" > /dev/null 2>&1

echo "$(date): 텔레그램 전송 완료" >> "$LOG_FILE"

# Ubuntu 알림
notify-send -i dialog-warning "이벤트 플래시" "트리거 감지 — 텔레그램 확인" 2>/dev/null || true

# 30일 이상 된 로그 삭제
find "$LOG_DIR" -name "flash_*.log" -mtime +30 -delete 2>/dev/null || true
