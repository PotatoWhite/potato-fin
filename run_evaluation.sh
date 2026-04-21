#!/bin/bash
# Evaluation 실행 — 예측 vs 실제 정산 + 적중률 + 편향 측정
# Usage: run_evaluation.sh [weekly|monthly|quarterly]

set -euo pipefail

unset CLAUDECODE 2>/dev/null || true

STOCK_DIR="${STOCK_DIR:-/home/bravopotato/Spaces/finspace/potato-fin}"
PYTHON="${PYTHON:-$STOCK_DIR/.venv/bin/python3}"
CLAUDE="${CLAUDE:-$(command -v claude 2>/dev/null || echo /home/bravopotato/.npm-global/bin/claude)}"
LOG_DIR="${LOG_DIR:-$HOME/logs/stock-monitor}"
MODE="${1:-weekly}"   # weekly | monthly | quarterly

mkdir -p "$LOG_DIR" "$STOCK_DIR/team/evaluations"
LOG_FILE="$LOG_DIR/evaluation_${MODE}_$(date +%Y%m%d_%H%M%S).log"

echo "$(date): Evaluation 시작 (mode=$MODE)" | tee -a "$LOG_FILE"

cd "$STOCK_DIR"

# --- 1단계: 데이터 집계 ---
SUMMARY=$("$PYTHON" - <<PYEOF
"""Evaluation 데이터 집계."""
import json
from datetime import datetime, timedelta
from pathlib import Path

STOCK_DIR = Path("$STOCK_DIR")
mode = "$MODE"

# thesis.json 현재 상태
thesis_path = STOCK_DIR / "investment_thesis.json"
if thesis_path.exists():
    thesis = json.loads(thesis_path.read_text())
else:
    thesis = {}

# global accuracy
acc = thesis.get("accuracy", {})
print(f"=== 전체 accuracy ===")
print(f"total_predictions: {acc.get('total_predictions', 0)}")
print(f"direction_correct: {acc.get('direction_correct', 0)}")
print(f"direction_rate: {acc.get('direction_rate', 0)}%")
print(f"avg_error_pct: {acc.get('avg_error_pct', 0)}%")
print(f"systematic_bias: {acc.get('systematic_bias', 'none')}")
print()

# 종목별 bias_tracker
print(f"=== 종목별 (n>=5 인 것만) ===")
tickers = thesis.get("tickers", {})
sig_count = 0
for tk, d in tickers.items():
    bt = d.get("bias_tracker", {})
    n = int(bt.get("n_predictions", 0) or 0)
    if n >= 5:
        sig_count += 1
        hits = int(bt.get("direction_hits", 0) or 0)
        rate = hits / n * 100 if n else 0
        err = bt.get("avg_signed_error_pct", 0)
        print(f"  {tk}: n={n}, hits={hits}, rate={rate:.1f}%, bias={err:+.2f}%")

if sig_count == 0:
    print("(n>=5 종목 없음 — 데이터 축적 중)")
print(f"총 유의미 종목: {sig_count}/19")

# 보고서 생성 성공률
reports_dir = STOCK_DIR / "보고서"
if reports_dir.exists():
    us_reports = list(reports_dir.glob("20*.md"))
    kr_reports = list((reports_dir / "한국").glob("20*.md")) if (reports_dir / "한국").exists() else []

    days_map = {"weekly": 7, "monthly": 30, "quarterly": 90}
    days = days_map.get(mode, 7)
    cutoff = datetime.now() - timedelta(days=days)

    us_recent = sum(1 for f in us_reports if datetime.fromtimestamp(f.stat().st_mtime) > cutoff)
    kr_recent = sum(1 for f in kr_reports if datetime.fromtimestamp(f.stat().st_mtime) > cutoff)

    # 예상 cron 실행 (평일만)
    expected_us = sum(1 for i in range(days) if (datetime.now() - timedelta(days=i+1)).weekday() < 5)
    expected_kr = expected_us

    print(f"\n=== 최근 {days}일 보고서 생성 ===")
    print(f"US: {us_recent}/{expected_us} ({us_recent/expected_us*100:.0f}%)")
    print(f"KR: {kr_recent}/{expected_kr} ({kr_recent/expected_kr*100:.0f}%)")

# heartbeat 로그
hb_log = Path.home() / "logs/stock-monitor/heartbeat.log"
if hb_log.exists():
    lines = hb_log.read_text().splitlines()
    stale = sum(1 for l in lines if "stale" in l.lower() or "error" in l.lower())
    print(f"\n=== Heartbeat 로그 ===")
    print(f"총 라인: {len(lines)}, 에러/stale: {stale}")
PYEOF
)

echo "$SUMMARY" | tee -a "$LOG_FILE"

# --- 2단계: Claude 로 evaluation 보고서 작성 ---
EVAL_DATE=$(date +%Y-%m-%d)
case "$MODE" in
    weekly)
        WEEK=$(date +%Y-W%V)
        REPORT_FILE="team/evaluations/weekly_${WEEK}.md"
        ;;
    monthly)
        MONTH=$(date +%Y-%m)
        REPORT_FILE="team/evaluations/monthly_${MONTH}.md"
        ;;
    quarterly)
        Q=$(( ($(date +%-m) - 1) / 3 + 1 ))
        Y=$(date +%Y)
        REPORT_FILE="team/evaluations/quarterly_${Y}-Q${Q}.md"
        ;;
esac

echo "$(date): Claude evaluation 보고서 작성 → $REPORT_FILE" | tee -a "$LOG_FILE"

PROMPT=$(cat <<EOF
너는 potato-fin 시스템의 **Evaluation Lead**다. 현우(potato-quant) 페르소나 주도로, 수아(potato-devil) 비판 보완.

## 집계 데이터
$SUMMARY

## Evaluation 유형: $MODE
- weekly: 지난 주 예측 vs 실제, 간결 (50~80줄)
- monthly: 월간 적중률 + 종목별 best/worst 5 + S&P 대비 알파 (100~150줄)
- quarterly: 분기 PnL + 13F 비교 + 시스템 ROI 판정 (150~250줄)

## 출력 파일
$REPORT_FILE

## 보고서 구조

### 1. 핵심 메트릭 (표)
| 지표 | 값 | 기준 | 판정 |
|------|-----|------|------|
| 방향 적중률 | X% | ≥55% | ✅/⚠/🚨 |
| 평균 오차율 | X% | <3% | ... |
| Signed bias | ±X% | \|<2%\| | ... |
| 보고서 생성률 | X% | ≥95% | ... |
| heartbeat 에러 | X건 | 0 | ... |

### 2. 종목별 Breakdown (n>=5 만)

### 3. 개선 권고 1~3개 (구체적)
- "X 종목 예측 폐기 (n<10 + 오차 >10%)"
- "Y 항목 자동 트리거 추가"

### 4. 의사결정 트리거 (자동 flag)
- 방향 적중률 < 45% 3주 연속 → Alt B/C 전환 제안
- 오차율 > 10% 월평균 → 예측 레인지 ATR×1.5 확대
- 13F 괴리 > 30% → 추천 프레임워크 재평가

### 5. 한 줄 요약 (페르소나 톤)
현우: "적중률 X%, n=Y, 결론: ___"

## 제약
- 숫자 없으면 "측정 불가" 명시
- n<10 종목은 "통계적 무의미" 라벨
- 이전 평가와의 변화 명시 (있으면)
- vanity metric 경고 (수아 톤)
- 한국어
EOF
)

EXIT_CODE=0
"$CLAUDE" --model sonnet --dangerously-skip-permissions --print "$PROMPT" >> "$LOG_FILE" 2>&1 || EXIT_CODE=$?

echo "$(date): Claude 종료 (exit=$EXIT_CODE)" | tee -a "$LOG_FILE"

# --- 3단계: Notion 업로드 + Telegram ---
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
    bash "$STOCK_DIR/telegram_notify.sh" "$STOCK_DIR/$REPORT_FILE" "Evaluation ($MODE)" >> "$LOG_FILE" 2>&1 || true
fi

echo "$(date): Evaluation 종료 (mode=$MODE, exit=$EXIT_CODE)" | tee -a "$LOG_FILE"
exit $EXIT_CODE
