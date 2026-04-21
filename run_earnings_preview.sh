#!/bin/bash
# 실적 D-7 프리뷰 자동 생성 — 매일 06:30 KST 실행
# 1. earnings_scanner.py 로 D-14 이내 실적 스캔
# 2. D-7 이하 & 아직 프리뷰 없는 종목 찾기
# 3. 네이버 consensus + Claude Sonnet 호출 → 프리뷰 생성
# 4. Notion 📈 Earnings DB 업로드 + Telegram

set -euo pipefail

unset CLAUDECODE 2>/dev/null || true

STOCK_DIR="${STOCK_DIR:-/home/bravopotato/Spaces/finspace/potato-fin}"
PYTHON="${PYTHON:-$STOCK_DIR/.venv/bin/python3}"
CLAUDE="${CLAUDE:-$(command -v claude 2>/dev/null || echo /home/bravopotato/.npm-global/bin/claude)}"
LOG_DIR="${LOG_DIR:-$HOME/logs/stock-monitor}"

mkdir -p "$LOG_DIR" "$STOCK_DIR/보고서/earnings"
LOG_FILE="$LOG_DIR/earnings_$(date +%Y%m%d_%H%M%S).log"

echo "$(date): Earnings 프리뷰 시작" | tee -a "$LOG_FILE"

cd "$STOCK_DIR"

# 1) 실적 스캔
SCAN_FILE="/tmp/earnings_due.jsonl"
"$PYTHON" earnings_scanner.py > "$SCAN_FILE" 2>> "$LOG_FILE"

if [ ! -s "$SCAN_FILE" ]; then
    echo "$(date): 향후 14일 실적 없음 — 종료" | tee -a "$LOG_FILE"
    exit 0
fi

echo "$(date): 스캔 결과 $(wc -l < $SCAN_FILE)건" | tee -a "$LOG_FILE"

# 2) 각 종목별 D-7 이하 & preview 없는 것만
while IFS= read -r line; do
    TICKER=$("$PYTHON" -c "import sys,json; print(json.loads('''$line''').get('ticker',''))" 2>/dev/null || echo "")
    DATE=$("$PYTHON" -c "import sys,json; print(json.loads('''$line''').get('date',''))" 2>/dev/null || echo "")
    DDAY=$("$PYTHON" -c "import sys,json; print(json.loads('''$line''').get('dday',99))" 2>/dev/null || echo "99")

    if [ -z "$TICKER" ] || [ "$DDAY" -gt 7 ]; then
        continue
    fi

    REPORT_FILE="보고서/earnings/${TICKER//\//_}_preview_${DATE}.md"

    if [ -f "$REPORT_FILE" ]; then
        echo "$(date): $TICKER $DATE — 이미 프리뷰 있음, skip" | tee -a "$LOG_FILE"
        continue
    fi

    echo "$(date): $TICKER D-$DDAY ($DATE) 프리뷰 생성 중" | tee -a "$LOG_FILE"

    # 네이버 consensus + 현재가 수집
    CONSENSUS_JSON=$("$PYTHON" - <<PYEOF
import naver_finance as nf, json
c = nf.get_consensus("$TICKER") or {}
p = nf.get_price("$TICKER")
result = {
    "recomm_mean": c.get("recomm_mean"),
    "target_mean": c.get("target_mean"),
    "target_high": c.get("target_high"),
    "target_low": c.get("target_low"),
    "currency": c.get("currency"),
    "current_price": p,
}
# 한국 종목이면 수급도 추가
if "$TICKER".endswith((".KS", ".KQ")):
    f = nf.get_kr_investor_flow("$TICKER", days=5) or {}
    if f.get("summary"):
        result["kr_flow"] = f["summary"]
    fund = nf.get_kr_fundamentals("$TICKER") or {}
    result["kr_fund"] = {k: fund.get(k) for k in ["per", "pbr", "eps", "est_per", "est_eps", "foreign_rate_pct"] if fund.get(k) is not None}
print(json.dumps(result, ensure_ascii=False))
PYEOF
)

    PROMPT="너는 potato-fin **실적 프리뷰 분석가**. 태경(potato-trader) + 현우(potato-quant) + 성우(potato-tech) 3 페르소나 통합 관점.

## 대상
- **종목**: $TICKER
- **실적 발표**: $DATE (D-$DDAY)

## 네이버 실측 데이터
\`\`\`json
$CONSENSUS_JSON
\`\`\`

## 필수 분석

### 1. 컨센서스 대비 현재가 (현우)
- 애널 목표가 대비 업사이드/다운사이드 %
- 최근 4분기 EPS 추세 (WebSearch 로 보완)
- 컨센 상향/하향 최근 조정

### 2. 수급 signal (현우 + 태경)
- 한국 종목: 네이버 3일 수급 (위 json 참조)
- 미국: WebSearch로 공매도/내부자 Form 4/옵션 IV 확인
- expected move % 명시 (옵션 가격 기반)

### 3. 섹터/테마 (성우 해당 시)
- 동종 업계 이미 발표한 경쟁사 톤 (Q1 실적 시즌 중)
- AI/반도체 관련이면 HBM4/Rubin 타임라인 반영

### 4. 시나리오별 가격 영향 (태경)
**Beat** (확률 %): 예상 가격 +X%, 가장 잘 나올 세부지표
**In-line** (확률 %): +/-X% 변동, guidance 의존
**Miss** (확률 %): 예상 -X%, 취약 부분

### 5. 포지션 권장 (태경)
- 현재 포트 비중 (portfolio.db 확인)
- **권장 액션** (하나만): 신규매수/추가매수/유지/일부차익/전량매도/헷지/신규진입금지
- **Risk budget**: NAV × 0.3% = Risk \$, Stop = Miss 예상가 or ATR×2 중 타이트한 쪽, Size = Risk ÷ Stop distance

## 출력 파일
$REPORT_FILE

## 보고서 구조 (60~100줄)

1. 헤더 박스 (종목/실적일/D-day/컨센/현재가/내 포지션/한 줄 thesis)
2. 📊 컨센서스 vs 실적 확률 (표)
3. 📈 수급 signal (옵션 IV / 공매도 / 외인 / 내부자)
4. 🎯 시나리오별 영향 Beat/In-line/Miss (표 + 가격 변동)
5. 🛠 권장 액션 (Risk \$ / Stop / Size)
6. 📌 한 줄 요약

## 제약
- 100줄 이내
- 숫자 없으면 \"측정 불가\" 명시
- 확률 + 시점 명시
- 한국어"

    "$CLAUDE" --model sonnet --dangerously-skip-permissions --print "$PROMPT" >> "$LOG_FILE" 2>&1 || true

    if [ -f "$REPORT_FILE" ]; then
        echo "$(date): $TICKER 프리뷰 완료 → $REPORT_FILE" | tee -a "$LOG_FILE"
        bash "$STOCK_DIR/telegram_notify.sh" "$STOCK_DIR/$REPORT_FILE" "실적 프리뷰" >> "$LOG_FILE" 2>&1 || true
    else
        echo "$(date): $TICKER 프리뷰 파일 생성 실패" | tee -a "$LOG_FILE"
    fi

done < "$SCAN_FILE"

echo "$(date): Earnings 프리뷰 종료" | tee -a "$LOG_FILE"
