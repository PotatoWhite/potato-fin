#!/bin/bash
# 자기개선 루프 — 일요일 22:00 KST (weekly evaluation 1시간 뒤)
# 기존 run_improve.sh 대체. 이전 것: "이거 개선해" 불명확 프롬프트 → 검증 없이 main 병합.
# 신규: evaluation 결과 + 지표 근거 → 개선안 1~3개 → branch → 검증 → PR-only (자동 머지 X)

set -euo pipefail

unset CLAUDECODE 2>/dev/null || true

STOCK_DIR="${STOCK_DIR:-/home/bravopotato/Spaces/finspace/potato-fin}"
PYTHON="${PYTHON:-$STOCK_DIR/.venv/bin/python3}"
CLAUDE="${CLAUDE:-$(command -v claude 2>/dev/null || echo /home/bravopotato/.npm-global/bin/claude)}"
LOG_DIR="${LOG_DIR:-$HOME/logs/stock-monitor}"

mkdir -p "$LOG_DIR" "$STOCK_DIR/team/improvements"
LOG_FILE="$LOG_DIR/improve_$(date +%Y%m%d_%H%M%S).log"

echo "$(date): 자기개선 시작" | tee -a "$LOG_FILE"

cd "$STOCK_DIR"

# ─────────────────────────────────────────────────────
# 1) 입력 수집 — 지난 주 데이터 근거
# ─────────────────────────────────────────────────────
INPUT_DATA=$("$PYTHON" - <<'PYEOF'
"""자기개선 입력 — 가장 최근 weekly evaluation + thesis bias + heartbeat + git log."""
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

STOCK_DIR = Path("/home/bravopotato/Spaces/finspace/potato-fin")

# 1. 최신 weekly evaluation
eval_dir = STOCK_DIR / "team/evaluations"
weekly_files = sorted(eval_dir.glob("weekly_*.md"), reverse=True) if eval_dir.exists() else []
print("## 1. 최신 Weekly Evaluation")
if weekly_files:
    latest = weekly_files[0]
    print(f"파일: {latest.name}")
    text = latest.read_text(errors="ignore")[:3000]
    print(f"```\n{text}\n```")
else:
    print("(아직 없음 — evaluation 실행 전)")
print()

# 2. thesis bias
thesis_path = STOCK_DIR / "investment_thesis.json"
if thesis_path.exists():
    thesis = json.loads(thesis_path.read_text())
    print("## 2. Thesis Bias (종목별)")
    worst = []
    for tk, d in thesis.get("tickers", {}).items():
        bt = d.get("bias_tracker", {})
        n = int(bt.get("n_predictions", 0) or 0)
        err = abs(bt.get("avg_signed_error_pct", 0) or 0)
        if n >= 3 and err > 3:
            worst.append((tk, n, err))
    worst.sort(key=lambda x: -x[2])
    for tk, n, err in worst[:5]:
        print(f"- {tk}: n={n}, |bias|={err:.1f}%")
    if not worst:
        print("- (유의미 편향 없음 or 데이터 부족)")
print()

# 3. heartbeat 에러
hb = Path.home() / "logs/stock-monitor/heartbeat.log"
if hb.exists():
    lines = hb.read_text(errors="ignore").splitlines()[-100:]
    errs = [l for l in lines if any(k in l for k in ("ERROR", "stale", "missing"))]
    print(f"## 3. Heartbeat (최근 100줄 중 이상 {len(errs)}건)")
    for e in errs[-5:]:
        print(f"- {e[:120]}")
print()

# 4. 지난 7일 git log
try:
    log = subprocess.run(
        ["git", "log", "--since=7 days ago", "--oneline", "-20"],
        capture_output=True, text=True, cwd=str(STOCK_DIR), timeout=10,
    ).stdout.strip()
    print("## 4. 최근 git 커밋 (지난 7일)")
    print("```")
    print(log or "(없음)")
    print("```")
except Exception:
    pass
print()

# 5. 보고서 생성 성공률
reports_dir = STOCK_DIR / "보고서"
if reports_dir.exists():
    cutoff = datetime.now() - timedelta(days=7)
    cnt_us = sum(1 for f in reports_dir.glob("20*.md") if datetime.fromtimestamp(f.stat().st_mtime) > cutoff)
    cnt_kr = sum(1 for f in (reports_dir / "한국").glob("20*.md") if (reports_dir / "한국").exists() and datetime.fromtimestamp(f.stat().st_mtime) > cutoff)
    # 예상: 평일 5일
    print("## 5. 보고서 생성 (지난 7일)")
    print(f"- US: {cnt_us}/5 ({cnt_us/5*100:.0f}%)")
    print(f"- KR: {cnt_kr}/5 ({cnt_kr/5*100:.0f}%)")
PYEOF
)

# ─────────────────────────────────────────────────────
# 2) Claude Sonnet 호출 — 개선안 1~3개 도출
# ─────────────────────────────────────────────────────
IMPROVE_DATE=$(date +%Y-%m-%d)
BRANCH="improve/${IMPROVE_DATE}"
PROPOSAL_FILE="team/improvements/proposal_${IMPROVE_DATE}.md"

PROMPT="너는 potato-fin 자기개선 루프 리드. 지훈(architect) + 수아(devil) 페르소나 통합.

## 입력: 지난 주 시스템 데이터
$INPUT_DATA

## Task: 개선안 1~3개 도출

### 원칙
1. **수치 근거 있는 것만** — \"왠지 좋을 것 같아서\" 금지
2. **작은 범위** — 단일 파일 수정, diff 10줄 이내 선호
3. **검증 가능** — bash -n / python -m py_compile / smoke test 통과
4. **롤백 쉬움** — 복잡한 리팩토링 금지

### 우선 개선 대상 (안전한 순)
1. **파라미터 튜닝**:
   - alert_config.json 종목별 손절선/목표가 (ATR 기반 재계산)
   - portfolio_config.json risk_profile 수치
   - thesis bias 기반 예측 레인지 조정
2. **프롬프트 문구**:
   - docs/report_template_*.md 강화 문구
   - .claude/agents/*.md 페르소나 정의 개선
3. **감시 로직**:
   - check_heartbeat.sh stale 임계 조정
   - naver_finance NaN 방어 강화
4. **(신중) 코드 로직**: 구체 버그 확인된 것만

### 금지 (초반 자기개선에서는)
- 운영 cron 스크립트 (run_report.sh 등) 대규모 수정
- 새 기능 추가 (Scope creep)
- 페르소나 정의 대폭 재작성

## 출력

### 산출물 1: $PROPOSAL_FILE
형식:
\`\`\`markdown
# 자기개선 제안 ($IMPROVE_DATE)

## 근거 지표
- (입력 데이터에서 문제 식별)

## 제안 1: <한 줄 제목>
- 대상 파일: xxx.py / line N
- 변경 내용: (diff 형식)
- 예상 효과: (수치 가능하면)
- 검증 방법: bash -n / pytest / smoke test

## 제안 2~3: (같은 형식)

## 한 줄 요약
\"이번 주 X 문제 감지, Y 수정으로 Z 개선 예상\"
\`\`\`

### 산출물 2: 실제 patch (선택)
가능하면 각 제안에 해당하는 실제 파일 수정을 **미리보기 diff** 로. 사용자가 보고 결정.

## 제약
- 100줄 이내
- 한국어
- 확신 낮으면 \"미실행 제안\"으로 구분"

echo "$(date): Sonnet 개선안 도출 중" | tee -a "$LOG_FILE"
"$CLAUDE" --model sonnet --dangerously-skip-permissions --print "$PROMPT" >> "$LOG_FILE" 2>&1 || true

# ─────────────────────────────────────────────────────
# 3) git branch — 자동 머지 X, PR mode (사용자 확인 후)
# ─────────────────────────────────────────────────────
if [ ! -f "$PROPOSAL_FILE" ]; then
    echo "$(date): 제안 파일 생성 실패, 종료" | tee -a "$LOG_FILE"
    exit 1
fi

echo "$(date): 제안 파일 생성됨 → $PROPOSAL_FILE" | tee -a "$LOG_FILE"

# branch 생성
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    echo "$(date): $BRANCH 브랜치 이미 존재, skip" | tee -a "$LOG_FILE"
else
    git checkout -b "$BRANCH" 2>&1 | tee -a "$LOG_FILE" || true
    git add "$PROPOSAL_FILE"
    git commit -m "자기개선 제안 ${IMPROVE_DATE}" 2>&1 | tee -a "$LOG_FILE" || true
    git checkout main 2>&1 | tee -a "$LOG_FILE" || true
    echo "$(date): $BRANCH 에 제안 커밋. 사용자 확인 후 cherry-pick or merge." | tee -a "$LOG_FILE"
fi

# ─────────────────────────────────────────────────────
# 4) Notion + Telegram 알림 (개선 루프는 Critical 아님 → Findings)
# ─────────────────────────────────────────────────────
if [ -f "$STOCK_DIR/$PROPOSAL_FILE" ]; then
    bash "$STOCK_DIR/telegram_notify.sh" "$STOCK_DIR/$PROPOSAL_FILE" "자기개선 제안" >> "$LOG_FILE" 2>&1 || true
fi

echo "$(date): 자기개선 종료" | tee -a "$LOG_FILE"
