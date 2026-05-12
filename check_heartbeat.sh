#!/bin/bash
# Tier 3 heartbeat 감시 — run_report.sh / run_korea_report.sh 가 25시간+ 침묵하면 텔레그램 알람.
# 설계 전제:
#   - 각 Tier 3 스크립트 말미에 `date -Iseconds > ~/logs/stock-monitor/.heartbeat_{us,kr}` 을 심어둔다.
#   - 이 스크립트를 매시간 cron으로 돌린다.
#   - stale(25h+) → 1번만 텔레그램 경고, 회복되면 1번만 회복 통지.
#   - 같은 stale 상태에 중복 알림 금지 (.heartbeat_alert_sent 상태파일 사용).
#
# 의존성: bash + curl + coreutils (date/stat). 새 라이브러리 없음.
# 환경변수: .env 의 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 재사용.

set -uo pipefail  # -e 는 의도적으로 뺌 — curl 실패가 다음 채널 점검을 막으면 안 됨.

# 일요일(DOW=0): 보고서 스케줄 없음 → no-op (허위경보 방지)
DOW=$(date +%w)
if [[ "$DOW" == "0" ]]; then
    echo "[$(date -Iseconds)] Sunday — heartbeat check skipped (no reports scheduled)"
    exit 0
fi

STOCK_DIR="${STOCK_DIR:-/home/bravopotato/Spaces/finspace/potato-fin}"
LOG_DIR="${LOG_DIR:-$HOME/logs/stock-monitor}"
STALE_SECONDS="${STALE_SECONDS:-90000}"   # 25시간. 하루 1회 스케줄 + 1시간 버퍼.

HEARTBEAT_US="$LOG_DIR/.heartbeat_us"
HEARTBEAT_KR="$LOG_DIR/.heartbeat_kr"
STATE_FILE="$LOG_DIR/.heartbeat_alert_sent"

mkdir -p "$LOG_DIR"
touch "$STATE_FILE"

# .env 로드 (토큰/챗아이디)
if [[ -f "$STOCK_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    . "$STOCK_DIR/.env"
    set +a
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
    echo "[$(date -Iseconds)] ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정 — .env 확인"
    exit 1
fi

API="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"
NOW_EPOCH=$(date +%s)

# --- helper: 텔레그램 전송 (Markdown 실패 시 plain 재시도) ---
send_telegram() {
    local msg="$1"
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API/sendMessage" \
        --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
        --data-urlencode "text=${msg}" \
        --data-urlencode "parse_mode=Markdown" \
        --max-time 10)
    if [[ "$http_code" != "200" ]]; then
        # Markdown 파싱 실패 가능 — plaintext 재시도
        curl -s -o /dev/null -X POST "$API/sendMessage" \
            --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
            --data-urlencode "text=${msg}" \
            --max-time 10 || true
    fi
}

# --- helper: 상태파일에서 특정 채널 flag 조회/설정 ---
# 포맷: "us=stale\nkr=ok" (라인 단위)
get_state() {
    local channel="$1"
    grep -E "^${channel}=" "$STATE_FILE" 2>/dev/null | tail -1 | cut -d= -f2
}

set_state() {
    local channel="$1"
    local value="$2"
    local tmp
    tmp=$(mktemp)
    grep -vE "^${channel}=" "$STATE_FILE" 2>/dev/null > "$tmp" || true
    echo "${channel}=${value}" >> "$tmp"
    mv "$tmp" "$STATE_FILE"
}

# --- helper: 한 채널 점검 ---
check_channel() {
    local label="$1"         # "US" / "KR"
    local channel_key="$2"   # "us" / "kr"
    local hb_file="$3"
    local prev_state
    local current_state
    local age_hours_str

    prev_state=$(get_state "$channel_key")
    prev_state="${prev_state:-ok}"

    if [[ ! -f "$hb_file" ]]; then
        current_state="missing"
        age_hours_str="파일 없음"
    else
        local mtime age
        mtime=$(stat -c %Y "$hb_file" 2>/dev/null || echo 0)
        age=$(( NOW_EPOCH - mtime ))
        age_hours_str="$(( age / 3600 ))h $(( (age % 3600) / 60 ))m"
        if (( age > STALE_SECONDS )); then
            current_state="stale"
        else
            current_state="ok"
        fi
    fi

    # 상태 전이 판단
    if [[ "$prev_state" == "ok" && ( "$current_state" == "stale" || "$current_state" == "missing" ) ]]; then
        # ok → stale: 경고 발송
        local reason_line
        if [[ "$current_state" == "missing" ]]; then
            reason_line="heartbeat 파일이 존재하지 않는다. 스크립트가 한번도 성공 종료하지 못함."
        else
            reason_line="마지막 성공: ${age_hours_str} 전. 25h 임계 초과."
        fi
        local msg
        msg=$(cat <<EOF
🚨 *Tier 3 ${label} 보고서 사일런트 다운*
상태: ${current_state^^}
${reason_line}
파일: \`${hb_file}\`
확인: \`tail ~/logs/stock-monitor/${channel_key}_report.log\`
시각: $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M KST')
EOF
)
        send_telegram "$msg"
        set_state "$channel_key" "$current_state"
        echo "[$(date -Iseconds)] ALERT ${label}: ${prev_state} → ${current_state}"
    elif [[ ( "$prev_state" == "stale" || "$prev_state" == "missing" ) && "$current_state" == "ok" ]]; then
        # stale → ok: 회복 통지
        local msg
        msg=$(cat <<EOF
✅ *Tier 3 ${label} 보고서 회복*
상태: OK (마지막 성공 ${age_hours_str} 전)
파일: \`${hb_file}\`
시각: $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M KST')
EOF
)
        send_telegram "$msg"
        set_state "$channel_key" "ok"
        echo "[$(date -Iseconds)] RECOVER ${label}: ${prev_state} → ok"
    else
        # 상태 유지 — 로그만
        echo "[$(date -Iseconds)] ${label}: ${current_state} (age=${age_hours_str}, prev=${prev_state}) — no-op"
    fi
}

# 두 채널 모두 점검
check_channel "US"    "us" "$HEARTBEAT_US"
check_channel "KR"    "kr" "$HEARTBEAT_KR"

exit 0
