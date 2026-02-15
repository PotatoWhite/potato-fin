#!/bin/bash
# 보고서 알림 전송 (텔레그램 PDF)
# Usage: telegram_notify.sh <report_file> [label]

set -euo pipefail

STOCK_DIR="/home/bravopotato/Spaces/finspace/potato-fin"
PYTHON="$STOCK_DIR/.venv/bin/python3"
set -a
. "$STOCK_DIR/.env"
set +a

REPORT_FILE="${1:-}"
LABEL="${2:-보고서}"

if [[ -z "$REPORT_FILE" || ! -f "$REPORT_FILE" ]]; then
    echo "Error: 보고서 파일 없음: $REPORT_FILE"
    exit 1
fi

API="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"
CHAT_ID="${TELEGRAM_CHAT_ID}"
REPORT_NAME=$(basename "$REPORT_FILE")
PDF_FILE="${REPORT_FILE%.md}.pdf"

# 1) MD → PDF 변환
"$PYTHON" "$STOCK_DIR/md_to_pdf.py" "$REPORT_FILE" "$PDF_FILE" 2>/dev/null
PDF_OK=$?

# 2) 텔레그램 알림
MSG="📊 *${LABEL} 생성 완료*
📄 \`${REPORT_NAME}\`
🕐 $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M KST')"

curl -s -X POST "$API/sendMessage" \
    -d chat_id="$CHAT_ID" \
    -d text="$MSG" \
    -d parse_mode="Markdown" > /dev/null 2>&1

# 3) PDF 전송
if [[ $PDF_OK -eq 0 && -f "$PDF_FILE" ]]; then
    curl -s -X POST "$API/sendDocument" \
        -F chat_id="$CHAT_ID" \
        -F document=@"$PDF_FILE" \
        -F caption="${LABEL} - ${REPORT_NAME%.md}.pdf" > /dev/null 2>&1
    echo "텔레그램 전송 완료: $PDF_FILE"
else
    curl -s -X POST "$API/sendDocument" \
        -F chat_id="$CHAT_ID" \
        -F document=@"$REPORT_FILE" \
        -F caption="${LABEL} - ${REPORT_NAME} (PDF 변환 실패)" > /dev/null 2>&1
    echo "텔레그램 전송 완료: $REPORT_FILE (PDF 변환 실패)"
fi

# 4) Ubuntu 데스크톱 알림
notify-send -i document "${LABEL} 생성 완료" "$REPORT_NAME" 2>/dev/null || true
