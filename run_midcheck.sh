#!/bin/bash
# 장중 체크포인트 (Tier 2 — 미국장 오픈 1.5시간 후)
# 매일 01:00 KST 실행 → Claude Sonnet으로 장전 플레이북 점검
# 장전 브리핑의 시나리오가 맞는지 확인 + 수정
#
# 비용: ~$3-4/회 (Sonnet)

set -euo pipefail

unset CLAUDECODE 2>/dev/null || true

STOCK_DIR="${STOCK_DIR:-/home/bravopotato/Spaces/finspace/potato-fin}"
PYTHON="${PYTHON:-$STOCK_DIR/.venv/bin/python3}"
CLAUDE="${CLAUDE:-$(command -v claude 2>/dev/null || echo /home/bravopotato/.npm-global/bin/claude)}"
LOG_DIR="${LOG_DIR:-$HOME/logs/stock-monitor}"

mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/midcheck_$(date +%Y%m%d_%H%M%S).log"

echo "$(date): 장중 체크포인트 시작" >> "$LOG_FILE"

cd "$STOCK_DIR"

# 1단계: 실시간 포트폴리오 현황
echo "$(date): 주가 업데이트" >> "$LOG_FILE"
PORTFOLIO_DATA=$("$PYTHON" "$STOCK_DIR/주가_업데이트.py" 2>/dev/null)
echo "$PORTFOLIO_DATA" >> "$LOG_FILE"

# 2단계: Tier 1 구조화 요약
MONITOR_SUMMARY=$("$PYTHON" -c "
from news_monitor import format_daily_briefing
print(format_daily_briefing())
" 2>/dev/null || echo "Tier 1 데이터 없음")

# 2.5단계: 투자 테제 로드
echo "$(date): 투자 테제 로드" >> "$LOG_FILE"
THESIS_SUMMARY=$("$PYTHON" -c "
from update_thesis import format_thesis_summary
print(format_thesis_summary())
" 2>/dev/null || echo "투자 테제 없음")

# 3단계: 오늘 장전 브리핑 찾기
TODAY=$(TZ=Asia/Seoul date +%Y-%m-%d)
PREMARKET_BRIEF=$(ls -1 "$STOCK_DIR/보고서/브리핑/${TODAY}"*.md 2>/dev/null | tail -1 || echo "")
echo "$(date): 장전 브리핑: $PREMARKET_BRIEF" >> "$LOG_FILE"

# 4단계: alert_config.json
ALERT_CONFIG=$(cat "$STOCK_DIR/alert_config.json" 2>/dev/null || echo '{}')

# 5단계: 오늘 트리거 누적
DAILY_FILE="$STOCK_DIR/data/monitor/${TODAY}.json"
DAILY_TRIGGERS=""
if [[ -f "$DAILY_FILE" ]]; then
    DAILY_TRIGGERS=$("$PYTHON" -c "
import json
with open('$DAILY_FILE') as f: data=json.load(f)
triggers = []
for s in data:
    for t in s.get('triggers', []):
        triggers.append(f\"{t.get('timestamp','')} | {t.get('type','')} | {t.get('ticker',t.get('event',''))} | {', '.join(t.get('alerts',t.get('headlines',['']))[:2])}\")
if triggers:
    print('오늘 트리거:')
    print('\n'.join(triggers[-10:]))
else:
    print('오늘 트리거 없음')
" 2>/dev/null || echo "데이터 없음")
fi

# 6단계: Claude Sonnet으로 체크포인트 작성
REPORT_TIME=$(TZ=Asia/Seoul date +%H%M)
CHECK_FILE="보고서/브리핑/${TODAY}_${REPORT_TIME}_mid.md"

echo "$(date): Claude 체크포인트 작성 → $CHECK_FILE" >> "$LOG_FILE"

"$CLAUDE" -p "장중 체크포인트를 작성하라. 미국장 오픈 1.5시간 경과 시점.

=== 저장 경로 ===
$CHECK_FILE

=== 현재 시간 ===
${TODAY} ${REPORT_TIME:0:2}:${REPORT_TIME:2:2} KST (미장 오픈 후 약 1.5시간)

=== 핵심 원칙 ===
장전 브리핑의 플레이북이 지금 맞고 있는가?
시나리오 A/B/C 중 어디로 가고 있는가?
플레이북 수정이 필요한가?

WebSearch를 활용하여 조사하라 (최소 5건):
1. S&P500/나스닥 현재 등락 + 주요 종목 동향
2. 장 초반 거래량, 섹터 리더/래거
3. 오늘 발표된 경제지표 결과 (있으면)
4. 보유종목 실시간 동향 (뉴스, 가격, 거래량)
5. VIX, 채권, 환율 방향

=== 보고서 템플릿 ===

\`\`\`markdown
# 장중 체크포인트 (${TODAY} ${REPORT_TIME:0:2}:${REPORT_TIME:2:2})

> S&P500: __ (등락%) | 나스닥: __ (등락%) | VIX: __

## 현재 시나리오 판정
**시나리오 __** 진행 중 (장전 브리핑 대비 __% 적중)
- 근거: (왜 이 시나리오인지)
- 괴리: (예상과 다른 점)

## 보유종목 현황
| 종목 | 현재가 | 등락% | 장전 예상 대비 | 조치 필요 |
(장전 브리핑의 예상 vs 실제 비교)

## 플레이북 수정사항
- (변경 1: 예를 들어 손절선 조정)
- (변경 2: 예를 들어 매수 조건 변경)
- (변경 없으면 '플레이북 유지')

## 오늘 트리거 이벤트
(Tier 1 감시에서 감지된 이상 정리)

## 남은 장 대응
- (마감까지 해야 할 것 + 안 해야 할 것)
\`\`\`

=== 장전 브리핑 (오늘) ===
브리핑 경로: $PREMARKET_BRIEF
반드시 Read하여 시나리오 A/B/C와 종목별 액션을 확인하고, 현재 어떤 시나리오가 진행 중인지 판정하라.

=== Tier 1 감시 요약 ===
$MONITOR_SUMMARY

=== 오늘 트리거 상세 ===
$DAILY_TRIGGERS

=== 포트폴리오 현황 ===
$PORTFOLIO_DATA

=== 투자 테제 (누적 판단) ===
아래는 이전 보고서들에서 누적된 투자 판단이다. 시나리오 판정 시 참조하라.
$THESIS_SUMMARY

=== 알림 설정 ===
$ALERT_CONFIG" \
    --allowedTools "WebSearch,WebFetch,Read,Write,Glob,Grep" \
    --permission-mode bypassPermissions \
    --model sonnet \
    --max-budget-usd 4.0 \
    >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "$(date): 체크포인트 완료 (exit=$EXIT_CODE)" >> "$LOG_FILE"

# 텔레그램 전송 (PDF)
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$CHECK_FILE" ]]; then
    echo "$(date): 텔레그램 전송" >> "$LOG_FILE"
    bash "$STOCK_DIR/telegram_notify.sh" "$STOCK_DIR/$CHECK_FILE" "장중 체크" >> "$LOG_FILE" 2>&1 || true
fi

# 30일 이상 된 로그 삭제
find "$LOG_DIR" -name "midcheck_*.log" -mtime +30 -delete 2>/dev/null || true

exit $EXIT_CODE
