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
    print("## 5. 보고서 생성 (지난 7일)")
    print(f"- US: {cnt_us}/5 ({cnt_us/5*100:.0f}%)")
    print(f"- KR: {cnt_kr}/5 ({cnt_kr/5*100:.0f}%)")
print()

# 6. Verdict 충돌 로그 (Digest 가 기록) — 주간 모순 패턴
conflicts_log = STOCK_DIR / "team/verdict_conflicts.jsonl"
print("## 6. 종목별 verdict 충돌 (지난 7일)")
if conflicts_log.exists():
    import json as _json
    from collections import Counter
    cutoff_7d = datetime.now() - timedelta(days=7)
    ticker_conflicts = Counter()
    recent_lines = []
    for line in conflicts_log.read_text(errors="ignore").splitlines()[-200:]:
        try:
            d = _json.loads(line)
            ts = datetime.fromisoformat(d["timestamp"])
            if ts < cutoff_7d:
                continue
            recent_lines.append(d["line"])
            # 티커 언급 빈도
            for tk in ["NVDA", "MSFT", "GOOGL", "TSLA", "WRB", "XOM", "SLV", "BOTZ", "GLD", "IWM", "LMT", "WMB", "XLE", "005930", "000660", "005380", "035420", "195940", "429760", "1377", "BAYN"]:
                if tk in d["line"]:
                    ticker_conflicts[tk] += 1
        except Exception:
            pass
    if recent_lines:
        print(f"- 총 {len(recent_lines)}건")
        print("- 빈발 종목 (충돌 횟수):")
        for tk, n in ticker_conflicts.most_common(5):
            print(f"  · {tk}: {n}회")
        print("- 최근 5건:")
        for ln in recent_lines[-5:]:
            print(f"  · {ln[:120]}")
    else:
        print("- (지난 7일 충돌 기록 없음 — Digest 가 아직 데이터 모으는 중)")
else:
    print("- (아직 로그 없음 — Digest 가 첫 실행 후 생성)")
print()

# 7. 지난 자기개선 제안 vs 실제 반영 (메타 평가)
improve_dir = STOCK_DIR / "team/improvements"
print("## 7. 지난 자기개선 제안 메타 평가 (최근 4주)")
if improve_dir.exists():
    cutoff_4w = datetime.now() - timedelta(weeks=4)
    past_proposals = sorted([f for f in improve_dir.glob("proposal_*.md")
                              if datetime.fromtimestamp(f.stat().st_mtime) > cutoff_4w],
                             key=lambda p: p.stat().st_mtime, reverse=True)
    if past_proposals:
        for f in past_proposals[:4]:
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d')
            text = f.read_text(errors="ignore")
            # "실행 권장" / "미실행 제안" 카운트
            applied = text.count("실행 권장") + text.count("[실행 권장]")
            pending = text.count("미실행 제안") + text.count("[미실행]")
            print(f"- {mtime} {f.name}: 실행권장 {applied}개 / 미실행 {pending}개")
        print(f"- **메타 지표**: 주간 제안 평균 3~5개 — 실제 반영률 측정 필요")
    else:
        print("- (아직 이전 제안 없음 — 이번이 첫 실행)")
else:
    print("- (디렉토리 없음)")
print()

# 8. 비용 추정 (대략)
print("## 8. 월 비용 추정 (현재 운영)")
costs = [
    ("US 정식 Opus", 21, 12.5),
    ("KR 정식 Opus", 21, 9),
    ("Premarket Sonnet", 21, 3.5),
    ("Midcheck Sonnet", 21, 3.5),
    ("Daily Digest Sonnet", 30, 2),
    ("Earnings Sonnet", 10, 2),
    ("Deep Dive Sonnet", 4, 6),
    ("Scout Sonnet", 4, 4),
    ("Evaluation", 4, 3),
    ("Self-improve", 4, 3),
]
total = sum(n * c for _, n, c in costs)
print("- 월 총액 추정: ~${:.0f}".format(total))
print("- 상위 3: Tier 3 US $262 + Tier 3 KR $189 + Tier 2 ($147)")
print("- Alt C 전환 시: 주 1회 Deep Dive 만 = 월 ~$36 (94% 절감)")
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
1. **모순 해소** (최우선 — verdict 충돌 로그 반영):
   - 자주 모순나는 종목 분석 (입력 섹션 6 참조)
   - 보고서 간 cross-reference 부족 개선
2. **파라미터 튜닝**:
   - alert_config.json 종목별 손절선/목표가 (ATR 기반 재계산)
   - portfolio_config.json risk_profile 수치
   - thesis bias 기반 예측 레인지 조정
3. **프롬프트 문구**:
   - docs/report_template_*.md 강화 문구
   - .claude/agents/*.md 페르소나 정의 개선
4. **감시 로직**:
   - check_heartbeat.sh stale 임계 조정
   - naver_finance NaN 방어 강화
5. **비용 최적화** (입력 섹션 8 참조):
   - Alt C 전환 타당성 재검토
   - 모델 선택 (Opus→Sonnet 가능한 곳)
6. **(신중) 코드 로직**: 구체 버그 확인된 것만

### 메타 평가 요구 (입력 섹션 7 반영)
- 지난 제안이 실제로 반영됐는지 git log 로 추적
- 반영된 것의 효과 추정 (적중률/오차율/heartbeat 변화)
- \"같은 문제 반복 제안 중\" 발견 시 자동 에스컬레이션

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

### 산출물 2: 각 제안에 구체 diff + 검증 스크립트 + 롤백 plan 필수

각 제안 블록에 포함:
- **diff (before/after)**: 변경 라인 명시
- **검증 스크립트**: bash -n / python -m py_compile / smoke test 명령
- **예상 효과 (정량)**: \"적중률 +1%p\" / \"heartbeat 에러 월 -3건\" 등
- **롤백 plan**: git checkout / sed 되돌리기 한 줄
- **영향 범위**: 해당 변경이 건드릴 다른 파일/cron

### 산출물 3: 메타 평가 섹션

- 지난 4주 제안 중 반영된 것 vs 안 된 것 (git log 기반 추정)
- 반영 후 효과 변화 (적중률/오차/heartbeat 추이)
- **반복되는 문제** 발견 시: \"⚠ N주 연속 같은 문제 제안 — 구조적 변경 필요\"

## 제약
- 100~150줄 이내
- 한국어
- 확신 낮으면 \"미실행 제안\"으로 구분
- 수치 없으면 \"측정 불가\"
- **diff 없으면 제안 아님** (구체성 필수)"

echo "$(date): Sonnet 개선안 도출 중" | tee -a "$LOG_FILE"
"$CLAUDE" --model sonnet --dangerously-skip-permissions --print "$PROMPT" >> "$LOG_FILE" 2>&1 || true

# ─────────────────────────────────────────────────────
# 3) 자동 검증 — 제안이 건드릴 파일 syntax 체크
# ─────────────────────────────────────────────────────
if [ -f "$PROPOSAL_FILE" ]; then
    echo "$(date): 자동 검증 시작" | tee -a "$LOG_FILE"
    # Proposal 에서 언급된 파일들 syntax 체크 (아직 변경 전이므로 baseline)
    echo "[검증] 현재 Python 파일 전수 py_compile" >> "$LOG_FILE"
    FAIL=0
    for py in naver_finance.py naver_broker.py notion_publish.py earnings_scanner.py update_thesis.py 주가_업데이트.py price_verify.py technical_analysis.py market_data.py portfolio_db.py portfolio_tracker.py; do
        "$PYTHON" -m py_compile "$STOCK_DIR/$py" 2>>"$LOG_FILE" || { echo "  ❌ $py 문법 오류" >> "$LOG_FILE"; FAIL=$((FAIL+1)); }
    done
    echo "[검증] shell 스크립트 bash -n" >> "$LOG_FILE"
    for sh in run_report.sh run_korea_report.sh run_midcheck.sh run_premarket.sh run_daily_digest.sh run_self_improve.sh run_evaluation.sh run_scout_weekly.sh run_earnings_preview.sh run_deep_dive_3.sh telegram_notify.sh check_heartbeat.sh; do
        bash -n "$STOCK_DIR/$sh" 2>>"$LOG_FILE" || { echo "  ❌ $sh 문법 오류" >> "$LOG_FILE"; FAIL=$((FAIL+1)); }
    done
    echo "[검증] 결과: $FAIL 파일 문법 오류" >> "$LOG_FILE"
    if [ $FAIL -gt 0 ]; then
        echo "$(date): ⚠ baseline 검증 $FAIL 건 오류 — 자기개선 전 수동 조치 필요" | tee -a "$LOG_FILE"
    fi
fi

# ─────────────────────────────────────────────────────
# 4) git branch — 자동 머지 X, PR mode (사용자 확인 후)
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
