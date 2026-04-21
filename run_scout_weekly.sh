#!/bin/bash
# 주간 숨은진주 스카우트 — 매주 금 16:00 KST (한국 장 마감 직후)
# 시우(potato-scout) 페르소나 기반. 14개 체크리스트 스캔.

set -euo pipefail

unset CLAUDECODE 2>/dev/null || true

STOCK_DIR="${STOCK_DIR:-/home/bravopotato/Spaces/finspace/potato-fin}"
PYTHON="${PYTHON:-$STOCK_DIR/.venv/bin/python3}"
CLAUDE="${CLAUDE:-$(command -v claude 2>/dev/null || echo /home/bravopotato/.npm-global/bin/claude)}"
LOG_DIR="${LOG_DIR:-$HOME/logs/stock-monitor}"

mkdir -p "$LOG_DIR" "$STOCK_DIR/보고서/스카우트"
LOG_FILE="$LOG_DIR/scout_$(date +%Y%m%d_%H%M%S).log"

echo "$(date): 주간 스카우트 시작" | tee -a "$LOG_FILE"

cd "$STOCK_DIR"

# 1) 한국 5종목 외인+기관 매수 신호 수집 (최근 3일)
KR_FLOW=$("$PYTHON" - <<'PYEOF'
import naver_finance as nf
import sys
sys.path.insert(0, '/home/bravopotato/Spaces/finspace/potato-fin')

# 보유 5종목 + 편입 후보 리서치 대상
CANDIDATES = [
    # 반도체 / AI
    "042700.KS",  # 한미반도체
    "328130.KQ",  # 루닛
    "093320.KQ",  # 케이아이엔엑스
    # 방산
    "012450.KS",  # 한화에어로스페이스
    "064350.KS",  # 현대로템
    # 바이오
    "214450.KS",  # 파마리서치프로덕트
    # 조선
    "009540.KS",  # HD한국조선해양
    "010140.KS",  # 삼성중공업
    # 금융
    "055550.KS",  # 신한지주
    "086790.KS",  # 하나금융지주
]

print("=== 외인+기관 매수 + 개인 매도 스캔 (최근 3일) ===")
hits = []
for tk in CANDIDATES:
    try:
        f = nf.get_kr_investor_flow(tk, days=3)
        if f and f.get("summary"):
            s = f["summary"]
            # 최강 매수 신호: 외+기 매수 AND 개인 매도
            if s["foreign_net_total"] > 0 and s["organ_net_total"] > 0 and s["individual_net_total"] < 0:
                hits.append({
                    "ticker": tk,
                    "foreign": s["foreign_net_total"],
                    "organ": s["organ_net_total"],
                    "individual": s["individual_net_total"],
                    "foreign_hold": s.get("foreign_hold_latest"),
                })
                print(f"✅ {tk}: 외 {s['foreign_net_total']:+,} / 기 {s['organ_net_total']:+,} / 개 {s['individual_net_total']:+,}")
    except Exception as e:
        print(f"  {tk} 조회 실패: {e}", file=sys.stderr)

print(f"\n총 히트: {len(hits)}/{len(CANDIDATES)}개")
PYEOF
)

echo "$KR_FLOW" | tee -a "$LOG_FILE"

# 2) Claude Sonnet 호출 — 시우 페르소나
REPORT_DATE=$(date +%Y-%m-%d_%H%M)
REPORT_FILE="보고서/스카우트/weekly_${REPORT_DATE}.md"

PROMPT=$(cat <<EOF
너는 **시우 (potato-scout)** 페르소나다.
정의: /home/bravopotato/Spaces/finspace/potato-fin/.claude/agents/potato-scout.md 를 Read하고 따라라.

## 이번 주 한국 매수 신호 사전 스캔 결과
$KR_FLOW

## 주간 스카우트 Task

1. 위 한국 매수 신호 hit 종목 각각의 **체크리스트 적용**
   - 시총 $1B~$30B 범위?
   - 일거래량 200K+?
   - 6M +50% / 1M +20% 급등 아닌가?
   - 애널 커버 5명 이하?
   - 재무 건전성?

2. **미국 숨은진주 3개 스카우트** (체크리스트 2개+ 충족):
   - 시총 $1B~$30B
   - 기관 +20% 매집 Q/Q
   - CEO/CFO 자발 매수 \$500K+ (10b5-1 제외)
   - 공매도 20%+ 실적 서프라이즈
   - 52주 신저가 + 기관 매집
   - 정책 수혜 비주류

3. **글로벌 숨은진주 1~2개**:
   - 일본 PBR<1 + 자사주
   - 유럽 방산 소형
   - 인도 중소형

4. **가장 확신 있는 후보 1개** 상세:
   - 티커, 시총, 체크리스트 N/14 충족
   - 진입 타이밍 (가격 조건)
   - 목표 Hold 기간
   - 기존 보유 19종목 대체 or 추가?

## 출력 파일
$REPORT_FILE

## 구조
- 한국 매수 신호 분석 (위 hit 종목 체크리스트 적용)
- 미국 숨은진주 3개 (각 10~15줄)
- 글로벌 숨은진주 1~2개
- 주간 Top Pick 1개 (상세)
- 이번 주 놓친 것 / 다음 주 주목

## 제약
- 기존 보유 19종목 제외 (태경 영역)
- 급등 회피 (1M +20% / 6M +50%)
- 시총 $1B~$30B 범위
- 체크리스트 N/14 명시
- 한국어
- 100~150줄 내
EOF
)

echo "$(date): Claude 스카우트 시작" | tee -a "$LOG_FILE"

EXIT_CODE=0
"$CLAUDE" --model sonnet --dangerously-skip-permissions --print "$PROMPT" >> "$LOG_FILE" 2>&1 || EXIT_CODE=$?

echo "$(date): Claude 종료 (exit=$EXIT_CODE)" | tee -a "$LOG_FILE"

# 3) Notion + Telegram
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
    bash "$STOCK_DIR/telegram_notify.sh" "$STOCK_DIR/$REPORT_FILE" "주간 스카우트" >> "$LOG_FILE" 2>&1 || true
fi

exit $EXIT_CODE
