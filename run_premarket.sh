#!/bin/bash
# 장전 브리핑 (Tier 2 — 미국장 오픈 1시간 전)
# 매일 21:30 KST 실행 → Claude Sonnet으로 오늘의 매매 플레이북 생성
# Tier 1 누적 데이터를 입력으로 활용
#
# 비용: ~$3-4/회 (Sonnet)

set -euo pipefail

unset CLAUDECODE 2>/dev/null || true

STOCK_DIR="${STOCK_DIR:-/home/bravopotato/Spaces/finspace/potato-fin}"
PYTHON="${PYTHON:-$STOCK_DIR/.venv/bin/python3}"
CLAUDE="${CLAUDE:-/home/linuxbrew/.linuxbrew/bin/claude}"
LOG_DIR="${LOG_DIR:-$HOME/logs/stock-monitor}"

mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/premarket_$(date +%Y%m%d_%H%M%S).log"

echo "$(date): 장전 브리핑 시작" >> "$LOG_FILE"

cd "$STOCK_DIR"

# 1단계: 주가 업데이트 (포트폴리오 현황)
echo "$(date): 주가 업데이트" >> "$LOG_FILE"
PORTFOLIO_DATA=$("$PYTHON" "$STOCK_DIR/주가_업데이트.py" 2>/dev/null)
echo "$PORTFOLIO_DATA" >> "$LOG_FILE"

# 2단계: Tier 1 구조화 요약 로드
echo "$(date): Tier 1 데이터 로드" >> "$LOG_FILE"
TODAY=$(TZ=Asia/Seoul date +%Y-%m-%d)
MONITOR_SUMMARY=$("$PYTHON" -c "
from news_monitor import format_daily_briefing
print(format_daily_briefing('$TODAY'))
" 2>/dev/null || echo "Tier 1 데이터 없음")

# 2.5단계: 투자 테제 로드
echo "$(date): 투자 테제 로드" >> "$LOG_FILE"
THESIS_SUMMARY=$("$PYTHON" -c "
from update_thesis import format_thesis_summary
print(format_thesis_summary())
" 2>/dev/null || echo "투자 테제 없음")

# 3단계: alert_config.json (손절/목표)
ALERT_CONFIG=$(cat "$STOCK_DIR/alert_config.json" 2>/dev/null || echo '{}')

# 4단계: 현금 잔고
CASH_DATA=$(cat "$STOCK_DIR/portfolio_config.json" 2>/dev/null || echo '{"cash":{"USD":0}}')

# 5단계: 직전 보고서의 5거래일 전망 (오늘의 기준선)
PREV_REPORT=$(ls -1 "$STOCK_DIR/보고서/"*.md 2>/dev/null | tail -1 || echo "")
echo "$(date): 직전 보고서: $PREV_REPORT" >> "$LOG_FILE"

# 6단계: Claude Sonnet으로 장전 브리핑 생성
REPORT_DATE=$(TZ=Asia/Seoul date +%Y-%m-%d)
REPORT_TIME=$(TZ=Asia/Seoul date +%H%M)
BRIEF_FILE="보고서/브리핑/${REPORT_DATE}_${REPORT_TIME}.md"

mkdir -p "$STOCK_DIR/보고서/브리핑"

echo "$(date): Claude 브리핑 작성 시작 → $BRIEF_FILE" >> "$LOG_FILE"

"$CLAUDE" -p "미국장 장전 브리핑을 작성하라. 장 오픈 1시간 전 기준.

=== 저장 경로 ===
$BRIEF_FILE

=== 현재 시간 ===
${REPORT_DATE} ${REPORT_TIME:0:2}:${REPORT_TIME:2:2} KST
미국장 오픈: 23:30 KST (약 2시간 후)

=== 핵심 원칙 ===
이 브리핑의 목적은 '오늘 장에서 뭘 할 것인가'를 결정하는 것이다.
분석이 아니라 **실행 계획(playbook)**이다.
모든 내용은 '만약 X이면 Y를 한다' 형태로 작성.

WebSearch를 활용하여 아래를 조사하라 (최소 8건):
1. 프리마켓 주요 종목 동향 (NVDA, TSLA, MSFT, GOOGL 등)
2. 아시아/유럽 세션 결과 (KOSPI, 닛케이, DAX, FTSE)
3. 선물 동향 (S&P500, 나스닥, 다우 선물)
4. 오늘 발표 예정 경제지표 (시간, 컨센서스)
5. 오버나이트 주요 뉴스 (관세, 지정학, 연준 발언)
6. VIX, 원유, 금, 환율 동향
7. 보유종목 관련 프리마켓 뉴스/실적 발표
8. Unusual options activity / 프리마켓 거래량 이상

=== 보고서 템플릿 ===

\`\`\`markdown
# 장전 브리핑 (${REPORT_DATE})

> 🕘 ${REPORT_TIME:0:2}:${REPORT_TIME:2:2} KST | US 오픈까지 약 2시간
> S&P 선물: __ | 나스닥 선물: __ | VIX: __
> 원달러: __ | 금: __ | WTI: __

---

## 오버나이트 요약 (3줄)
1. (가장 중요한 것)
2. (두번째)
3. (세번째)

## 오늘의 이벤트
| 시간(KST) | 이벤트 | 컨센서스 | 예측(결과→영향) |
(오늘 발표 예정 경제지표 + 실적 + 정치 이벤트)

## 프리마켓 종목 현황
| 종목 | 프리마켓 | 등락% | 뉴스 | 오늘 전략 |
(보유종목 프리마켓 가격 + 오늘의 액션)

## 오늘의 플레이북

### 시나리오 A: 강세 오픈 (확률 _%)
- 조건: (선물 +0.5%+ / 경제지표 호조)
- 액션: (종목별 구체적 매수/매도)

### 시나리오 B: 횡보 오픈 (확률 _%)
- 조건: (선물 ±0.3%)
- 액션: (관망 또는 지정가 매수)

### 시나리오 C: 약세 오픈 (확률 _%)
- 조건: (선물 -0.5%+)
- 액션: (손절 확인 + 저가 매수 기회)

## 종목별 오늘 액션
| 종목 | 현재가 | 손절선 | 목표가 | 오늘 액션 | 조건 |
(반드시 alert_config.json의 손절/목표 반영)

## 주의사항
- (오늘 가장 조심할 것 1개)
- (매수 금지 종목 있으면 명시)
\`\`\`

=== Tier 1 감시 요약 ===
$MONITOR_SUMMARY

=== 포트폴리오 현황 ===
$PORTFOLIO_DATA

=== 종목별 알림 설정 (손절/목표) ===
$ALERT_CONFIG

=== 현금 잔고 ===
$CASH_DATA

=== 투자 테제 (누적 판단) ===
아래는 이전 보고서들에서 누적된 투자 판단이다. 오늘 플레이북 작성 시 참조하라.
- 확신도 높은 종목은 기존 방향 유지, 낮은 종목은 신중하게.
- 정확도/편향 정보를 반영하여 예상 가격을 보정하라.
$THESIS_SUMMARY

=== 직전 보고서 ===
직전 보고서 경로: $PREV_REPORT
이 파일을 Read하여 '5거래일 전망'의 오늘 예상을 참조하라." \
    --allowedTools "WebSearch,WebFetch,Read,Write,Glob,Grep" \
    --permission-mode bypassPermissions \
    --model sonnet \
    --max-budget-usd 4.0 \
    >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "$(date): 브리핑 생성 완료 (exit=$EXIT_CODE)" >> "$LOG_FILE"

# 텔레그램 전송 (PDF)
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$BRIEF_FILE" ]]; then
    echo "$(date): 텔레그램 전송" >> "$LOG_FILE"
    bash "$STOCK_DIR/telegram_notify.sh" "$STOCK_DIR/$BRIEF_FILE" "장전 브리핑" >> "$LOG_FILE" 2>&1 || true
fi

# 30일 이상 된 로그 삭제
find "$LOG_DIR" -name "premarket_*.log" -mtime +30 -delete 2>/dev/null || true

exit $EXIT_CODE
