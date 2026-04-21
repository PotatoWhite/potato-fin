#!/bin/bash
# 보고서 알림 전송 (Notion 업로드 + 텔레그램 링크)
# Round 2 태경/민지 권고: PDF 제거. Notion DB에 업로드하고 Telegram은 링크만.
# Usage: telegram_notify.sh <report_file> [label]
#   label = "US 보고서" | "한국 보고서" | "Deep Dive 3" | ...

set -euo pipefail

STOCK_DIR="${STOCK_DIR:-/home/bravopotato/Spaces/finspace/potato-fin}"
PYTHON="${PYTHON:-$STOCK_DIR/.venv/bin/python3}"
set -a
. "$STOCK_DIR/.env"
set +a

REPORT_FILE="${1:-}"
LABEL="${2:-보고서}"

if [[ -z "$REPORT_FILE" || ! -f "$REPORT_FILE" ]]; then
    echo "Error: 보고서 파일 없음: $REPORT_FILE"
    exit 1
fi

REPORT_NAME=$(basename "$REPORT_FILE")
API="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"
CHAT_ID="${TELEGRAM_CHAT_ID}"

# Label → Notion type 매핑
case "$LABEL" in
    "US 보고서"|"US report")      NOTION_TYPE="US" ;;
    "한국 보고서"|"KR report")     NOTION_TYPE="KR" ;;
    "Deep Dive 3")                 NOTION_TYPE="DeepDive" ;;
    "장전 브리핑"|"Premarket")     NOTION_TYPE="Premarket" ;;
    "장중 체크"|"Midcheck")        NOTION_TYPE="Midcheck" ;;
    "주간 스카우트"|"Scout")       NOTION_TYPE="Scout" ;;
    "실적 프리뷰"|"Earnings")      NOTION_TYPE="Earnings" ;;
    *)                             NOTION_TYPE="Findings" ;;
esac

# 텔레그램 알림 톤다운 — Notion 업로드는 유지, 알림만 끈다
# SILENT_TYPES: 이 타입은 Notion만, Telegram 안 보냄 (사용자가 Notion 앱에서 확인)
# ACTIVE: Critical + Daily Digest + Scout + Earnings D-7 만 알림
SILENT_TYPES=("US" "KR" "Premarket" "Midcheck" "DeepDive")
IS_SILENT=0
for s in "${SILENT_TYPES[@]}"; do
    [[ "$NOTION_TYPE" == "$s" ]] && IS_SILENT=1 && break
done

# 한 줄 요약 추출 (보고서 3번째 줄 헤더에서)
SUMMARY=$(sed -n '3p' "$REPORT_FILE" | sed 's/^> //; s/\*\*//g' | cut -c1-200 || echo "")

# 1) Notion 업로드 (integration token 없으면 non-fatal skip)
NOTION_URL=""
if PUBLISH_OUT=$("$PYTHON" "$STOCK_DIR/notion_publish.py" "$REPORT_FILE" "$NOTION_TYPE" --summary "$SUMMARY" 2>&1); then
    # 첫 줄이 URL 이면 추출
    if echo "$PUBLISH_OUT" | head -1 | grep -q "^https://www.notion.so/"; then
        NOTION_URL=$(echo "$PUBLISH_OUT" | head -1)
    fi
fi

# 2) 텔레그램 알림
MSG_HEADER="📊 *${LABEL} 생성 완료*
📄 \`${REPORT_NAME}\`
🕐 $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M KST')"

if [[ -n "$NOTION_URL" ]]; then
    MSG="${MSG_HEADER}
🔗 [Notion에서 열기](${NOTION_URL})"
else
    MSG="${MSG_HEADER}
📁 \`${REPORT_FILE}\`
⚠️ Notion 업로드 안 됨 (NOTION_TOKEN 미설정 또는 실패)"
fi

# SILENT 타입은 텔레그램 알림 skip (Notion 만 업로드됨)
if [[ "$IS_SILENT" == "1" ]]; then
    echo "[silent] $NOTION_TYPE → Notion 업로드만. 텔레그램 알림 skip. (Daily Digest 가 08:00 에 요약)"
    if [[ -n "$NOTION_URL" ]]; then
        echo "  Notion: $NOTION_URL"
    fi
    # Silent 모드에서도 Notion 업로드 실패 시는 fallback 알림 (파이프라인 붕괴 대비)
    if [[ -z "$NOTION_URL" ]]; then
        curl -s -X POST "$API/sendMessage" \
            -d chat_id="$CHAT_ID" \
            -d text="⚠️ ${LABEL} 생성됐으나 Notion 업로드 실패 — ${REPORT_FILE}" > /dev/null 2>&1 || true
    fi
else
    # Critical (Findings / Earnings / Scout / Digest) 는 알림 보냄
    curl -s -X POST "$API/sendMessage" \
        -d chat_id="$CHAT_ID" \
        -d text="$MSG" \
        -d parse_mode="Markdown" \
        -d disable_web_page_preview="false" > /dev/null 2>&1 \
        || curl -s -X POST "$API/sendMessage" \
            -d chat_id="$CHAT_ID" \
            -d text="$MSG" > /dev/null 2>&1 || true

    # Notion 업로드 실패 시에만 MD 파일 직접 전송
    if [[ -z "$NOTION_URL" ]]; then
        curl -s -X POST "$API/sendDocument" \
            -F chat_id="$CHAT_ID" \
            -F document=@"$REPORT_FILE" \
            -F caption="${LABEL} - ${REPORT_NAME} (원본 MD, Notion 미업로드)" > /dev/null 2>&1 || true
        echo "텔레그램 전송: ${REPORT_FILE} (Notion 미업로드)"
    else
        echo "텔레그램 전송: Notion 링크 (${NOTION_URL})"
    fi
fi

# 4) 데스크톱 알림 (선택)
command -v notify-send >/dev/null 2>&1 && notify-send -i document "${LABEL} 생성 완료" "$REPORT_NAME" 2>/dev/null || true
