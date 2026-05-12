#!/bin/bash
# Deep Dive 3 — 주간 3종목 집중 분석 (수아 Alt C 파일럿)
# 선정 로직:
#   1. 최대 비중 종목 (portfolio_db.py)
#   2. 최악 예측 적중률 종목 (investment_thesis.json) — 현재 적중률 버그 있으므로 최대 bias 종목으로 대체
#   3. 최근 7일 최대 변동 종목 (주가_업데이트.py 스냅샷 기준)
#
# 각 종목 × 5 페르소나 (PM/퀀트/아키텍트/트레이더/악마) 순차 분석 → 1 문서
# 예상 비용: Sonnet × 3종목 × 5페르소나 ≈ $6/주 = $24/월 (vs 현재 $644/월, 94% 절감)
# 상태: PILOT (cron 미등록). 수동 실행으로 검증 먼저.

set -euo pipefail

unset CLAUDECODE 2>/dev/null || true

STOCK_DIR="${STOCK_DIR:-/home/bravopotato/Spaces/finspace/potato-fin}"
PYTHON="${PYTHON:-$STOCK_DIR/.venv/bin/python3}"
CLAUDE="${CLAUDE:-$(command -v claude 2>/dev/null || echo /home/bravopotato/.npm-global/bin/claude)}"
LOG_DIR="${LOG_DIR:-$HOME/logs/stock-monitor}"
MODEL="${MODEL:-sonnet}"   # Alt C 설계: Sonnet. opus 쓰고 싶으면 MODEL=opus ./run_deep_dive_3.sh

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/deep_dive_3_$(date +%Y%m%d_%H%M%S).log"

echo "$(date): Deep Dive 3 시작 (MODEL=$MODEL)" | tee -a "$LOG_FILE"

cd "$STOCK_DIR"

# --- 1단계: 주가/환율 최신화 ---
echo "$(date): 주가 업데이트" >> "$LOG_FILE"
"$PYTHON" "$STOCK_DIR/주가_업데이트.py" > /dev/null 2>&1 || true

# --- 2단계: 3종목 선정 ---
echo "$(date): 3종목 선정 중" | tee -a "$LOG_FILE"

SELECTED_TICKERS=$("$PYTHON" - <<'PYEOF'
"""Deep Dive 3 선정 로직."""
import json
import sqlite3
from pathlib import Path

STOCK_DIR = Path("/home/bravopotato/Spaces/finspace/potato-fin")

selected = []

# 1) 최대 비중 종목
try:
    conn = sqlite3.connect(STOCK_DIR / "portfolio.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker, SUM(shares * current_price_usd) AS value_usd
        FROM snapshots
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM snapshots)
        GROUP BY ticker
        ORDER BY value_usd DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    if row:
        selected.append((row[0], "max_weight"))
    conn.close()
except Exception as e:
    # Fallback — portfolio.db 스키마 변경 등 대비
    selected.append(("GOOGL", "max_weight_fallback"))

# 2) 최악 적중률 (현재 bias 가장 큰 종목으로 대체 — Round 2 현우 발견: 적중률 측정 불가)
try:
    with open(STOCK_DIR / "investment_thesis.json") as f:
        thesis = json.load(f)
    candidates = []
    for tk, d in thesis.get("tickers", {}).items():
        bt = d.get("bias_tracker", {})
        avg_err = abs(bt.get("avg_error_pct", 0) or 0)
        if avg_err > 0:
            candidates.append((tk, avg_err))
    candidates.sort(key=lambda x: -x[1])
    for tk, err in candidates:
        if tk not in [s[0] for s in selected]:
            selected.append((tk, f"worst_bias_{err:.1f}%"))
            break
except Exception:
    selected.append(("BAYN.DE", "worst_bias_fallback"))

# 3) 최근 7일 최대 변동 (portfolio.db realtime_prices 활용)
try:
    conn = sqlite3.connect(STOCK_DIR / "portfolio.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker, MAX(price) - MIN(price) AS range_, AVG(price) AS avg_price
        FROM realtime_prices
        WHERE captured_at >= datetime('now', '-7 days')
        GROUP BY ticker
        HAVING avg_price > 0
        ORDER BY (range_ / avg_price) DESC
        LIMIT 5
    """)
    rows = cur.fetchall()
    conn.close()
    for tk, rng, avg in rows:
        if tk not in [s[0] for s in selected]:
            pct = (rng / avg) * 100 if avg else 0
            selected.append((tk, f"max_volatility_{pct:.1f}%"))
            break
except Exception:
    # Fallback
    for fb in ["TSLA", "NVDA", "LMT"]:
        if fb not in [s[0] for s in selected]:
            selected.append((fb, "max_vol_fallback"))
            break

# 정확히 3개 보장
while len(selected) < 3:
    selected.append(("SPY_placeholder", "padding"))

print(",".join(f"{tk}:{reason}" for tk, reason in selected[:3]))
PYEOF
)

echo "$(date): 선정 결과: $SELECTED_TICKERS" | tee -a "$LOG_FILE"

# --- 3단계: 5 페르소나 × 3 종목 분석 (Claude CLI) ---
REPORT_DATE=$(date +%Y-%m-%d_%H%M)
REPORT_FILE="보고서/deep_dive_3/${REPORT_DATE}.md"
mkdir -p "$(dirname "$STOCK_DIR/$REPORT_FILE")"

PROMPT=$(cat <<EOF
너는 potato-fin의 Deep Dive 3 리드다. 이번 주 집중 분석 대상 3종목:

${SELECTED_TICKERS}

(형식: TICKER:SELECTION_REASON — 최대 비중 / 최악 bias / 최대 변동)

## 작업
각 종목에 대해 5 페르소나 관점으로 순차 분석한다:
1. **민지 (PM)** — 이 종목 관련 사용자 의사결정 1개만 (매수/홀드/매도/리밸런싱/관망 중 택 1). 근거 1줄.
2. **현우 (퀀트)** — investment_thesis.json에서 이 종목의 n_predictions, direction_hit_rate, bias. n<10이면 "측정 불가"로 명시.
3. **지훈 (아키텍트)** — 이 종목 알림/모니터링 설정(alert_config.json)의 구멍 한 가지. 없으면 "없음".
4. **태경 (트레이더)** — 액션 티켓 1장. Risk \$, Stop, Size 필수. NAV 대비 single_trade_risk_pct=0.003 기본.
5. **수아 (악마)** — 이 종목 보유 정당성 1줄 공격. 대안 1줄.

## 포맷
각 종목별 섹션. 총 3섹션. 각 섹션 25~40줄.
최상단에 "이번 주 결론 3줄" 박스 강제 (각 종목 한 줄).

## 주의
- 1062줄 보고서 생성 금지. 총 150줄 이내.
- 숨은 진주 발굴 / 거시 분석 / 정치 / 기관 자금흐름 섹션 **전부 금지**. 이건 Deep Dive 3이지 포괄 리서치 아님.
- 포지션 사이징은 태경 페르소나만, 리스크 금액 = NAV × 0.003 고정.
- 보고서 템플릿 (report_template_us.md) 따르지 마라. 최소 템플릿.

## 데이터 소스
- portfolio.db (SQLite)
- investment_thesis.json
- alert_config.json
- portfolio_config.json (risk_profile.single_trade_risk_pct 참조)
- docs/vertical_map.md (종목별 공급망/경쟁사 — 빠른 참조용)
- .claude/agents/potato-{pm,quant,architect,trader,devil}.md (각 페르소나 톤)
- **메르 컨텍스트**: 각 종목 시작 전 \`Bash("$STOCK_DIR/.venv/bin/python3 mer_context.py --ticker <티커> --days 90")\` 호출하여 메르 언급 확인. 있으면 민지/태경 섹션에 1~2줄 인용. 없으면 생략.

## 출력
보고서 파일: $REPORT_FILE

완료 후 "✅ Deep Dive 3 ($SELECTED_TICKERS) written to $REPORT_FILE" 한 줄 반환.
EOF
)

echo "$(date): Claude CLI 호출 ($MODEL)" | tee -a "$LOG_FILE"

EXIT_CODE=0
"$CLAUDE" --model "$MODEL" --dangerously-skip-permissions --print "$PROMPT" >> "$LOG_FILE" 2>&1 || EXIT_CODE=$?

echo "$(date): Claude 종료 (exit=$EXIT_CODE)" | tee -a "$LOG_FILE"

# --- 4단계: 텔레그램 전송 ---
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
    echo "$(date): 텔레그램 전송" | tee -a "$LOG_FILE"
    bash "$STOCK_DIR/telegram_notify.sh" "$STOCK_DIR/$REPORT_FILE" "Deep Dive 3" >> "$LOG_FILE" 2>&1 || true
fi

# --- 5단계: heartbeat (기존 시스템 호환) ---
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
    date -Iseconds > "$LOG_DIR/.heartbeat_deep_dive"
fi

echo "$(date): Deep Dive 3 종료 (exit=$EXIT_CODE)" | tee -a "$LOG_FILE"
exit $EXIT_CODE
