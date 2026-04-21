#!/bin/bash
# Daily Digest — 매일 08:00 KST
# 지난 24시간 간 모든 시스템 산출물을 1통 알림으로 통합.
# 목적: 텔레그램 알림 과부하 해결. 개별 보고서/플래시 조용해지고 이거 1건만 울림.

set -euo pipefail

unset CLAUDECODE 2>/dev/null || true

STOCK_DIR="${STOCK_DIR:-/home/bravopotato/Spaces/finspace/potato-fin}"
PYTHON="${PYTHON:-$STOCK_DIR/.venv/bin/python3}"
CLAUDE="${CLAUDE:-$(command -v claude 2>/dev/null || echo /home/bravopotato/.npm-global/bin/claude)}"
LOG_DIR="${LOG_DIR:-$HOME/logs/stock-monitor}"

mkdir -p "$LOG_DIR" "$STOCK_DIR/보고서/digest"
LOG_FILE="$LOG_DIR/digest_$(date +%Y%m%d_%H%M%S).log"

echo "$(date): Daily Digest 시작" | tee -a "$LOG_FILE"

cd "$STOCK_DIR"

DIGEST_DATE=$(date +%Y-%m-%d)
REPORT_FILE="보고서/digest/${DIGEST_DATE}.md"

# 지난 24시간 데이터 수집
CONTEXT=$("$PYTHON" - <<'PYEOF'
"""Digest 컨텍스트 수집."""
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
import subprocess

STOCK_DIR = Path(os.environ.get("STOCK_DIR", "/home/bravopotato/Spaces/finspace/potato-fin"))
LOG_DIR = Path(os.environ.get("LOG_DIR", os.path.expanduser("~/logs/stock-monitor")))

now = datetime.now()
cutoff = now - timedelta(hours=24)
cutoff_epoch = cutoff.timestamp()

print(f"## 📅 지난 24시간 (기준: {now.strftime('%Y-%m-%d %H:%M KST')})")
print()

# 1) 이벤트 플래시
print("### ⚡ 이벤트 플래시")
flash_files = sorted(LOG_DIR.glob("flash_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
flash_recent = [f for f in flash_files if f.stat().st_mtime > cutoff_epoch][:10]
if flash_recent:
    for f in flash_recent:
        text = f.read_text(errors="ignore")
        # 트리거 라인 추출
        lines = text.splitlines()
        ticker = "?"
        reason = "?"
        change = "?"
        for ln in lines:
            if "ticker" in ln: ticker = ln.split('"ticker":')[-1].strip(' ",')
            if "change_pct" in ln: change = ln.split('"change_pct":')[-1].strip(' ,')
            if "alerts" in ln:
                import re as _re
                m = _re.search(r'\["([^"]+)"', ln)
                if m: reason = m.group(1)
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime('%H:%M')
        print(f"- {mtime} {ticker} {change}% — {reason}")
else:
    print("- (없음)")
print()

# 2) 보고서 생성 실적
print("### 📊 보고서 생성 (지난 24h)")
for pattern, label in [
    ("report_*.log", "US 정식"),
    ("korea_report_*.log", "KR 정식"),
    ("premarket_*.log", "장전"),
    ("midcheck_*.log", "장중"),
    ("earnings_*.log", "실적 프리뷰"),
    ("deep_dive_*.log", "Deep Dive"),
    ("scout_*.log", "스카우트"),
]:
    files = sorted(LOG_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    recent = [f for f in files if f.stat().st_mtime > cutoff_epoch]
    if recent:
        for f in recent[:2]:
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime('%H:%M')
            size_kb = f.stat().st_size // 1024
            status = "✅" if size_kb > 1 else "⚠"
            print(f"- {mtime} {label}: {status} ({size_kb}KB)")
print()

# 3) heartbeat 상태
print("### 🫀 Heartbeat")
hb_log = LOG_DIR / "heartbeat.log"
if hb_log.exists():
    recent_errors = []
    for ln in hb_log.read_text(errors="ignore").splitlines()[-50:]:
        if any(k in ln for k in ("ERROR", "stale", "missing")):
            recent_errors.append(ln[:100])
    if recent_errors:
        print(f"- ⚠ {len(recent_errors)} 이상 감지:")
        for e in recent_errors[-3:]:
            print(f"  · {e}")
    else:
        print("- ✅ 정상 (지난 24h)")
print()

# 4) 포트폴리오 변동
print("### 💰 포트폴리오 상태")
try:
    import sys
    sys.path.insert(0, str(STOCK_DIR))
    from portfolio_db import get_db
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT snapshot_date, SUM(valuation_krw) as nav_krw, SUM(pnl_krw) as pnl_krw
        FROM snapshots
        WHERE snapshot_date >= datetime('now', '-2 days')
        GROUP BY snapshot_date
        ORDER BY snapshot_date DESC
        LIMIT 5
    """)
    rows = cur.fetchall()
    if rows:
        for d, nav, pnl in rows[:3]:
            nav_m = nav / 1_000_000 if nav else 0
            pnl_m = pnl / 1_000_000 if pnl else 0
            print(f"- {d}: NAV ₩{nav_m:.1f}M / PnL ₩{pnl_m:+.1f}M")
    conn.close()
except Exception as e:
    print(f"- (조회 실패: {e})")
print()

# 5) 오늘 예정 이벤트 (earnings)
print("### 📈 다가오는 실적 (D-7 이내)")
try:
    scan_out = subprocess.run(
        [str(STOCK_DIR / ".venv/bin/python3"), str(STOCK_DIR / "earnings_scanner.py")],
        capture_output=True, text=True, timeout=30,
    )
    for ln in scan_out.stdout.splitlines():
        try:
            d = json.loads(ln)
            dday = d.get("dday", 99)
            if dday <= 7:
                print(f"- D-{dday} {d.get('ticker')} ({d.get('date')}) 컨센 EPS {d.get('consensus_eps','?')}")
        except Exception:
            pass
except Exception as e:
    print(f"- (조회 실패: {e})")
print()
PYEOF
)

# Claude Sonnet 호출 — 컨텍스트 + 3-5 Today Action 생성
PROMPT="너는 potato-fin Daily Digest 생성자. 아침 1통 알림의 **유일한 정보원**이니 간결·액션 중심.

## 입력: 지난 24시간 시스템 데이터
$CONTEXT

## Task: Daily Digest 작성
### 필수 구조 (60~80줄 이내)

1. **🎯 오늘의 Top 3 Action** (가장 중요)
   - 위 데이터 + 최신 시장 상황 기반
   - 각 액션: 종목 / 가격 조건 / 사이즈 / 근거 1줄
   - 없으면 \"오늘 체결 액션 없음 — 관망 이유: X\"

2. **⚡ 간밤 이벤트 (Critical 3개)**
   - 이벤트 플래시 중 가장 중요한 3개만
   - 각 1줄 요약 + 포지션 영향

3. **📊 보고서 링크** (Notion 만 업로드된 것)
   - Premarket/Midcheck/US/KR 중 생성된 것 링크
   - 사용자가 **반드시 봐야 할 1개** 강조

4. **📈 이번 주 임박 실적** (D-7 이내만)

5. **⚠️ 이상 감지** (heartbeat 에러, 보고서 실패 등)

6. **🛌 한 줄 요약** (태경 페르소나 톤)

## 출력 파일
$REPORT_FILE

## 제약
- 위 입력에 없는 건 만들어내지 말 것
- 숫자 없으면 \"측정 불가\"
- 한국어
- 80줄 이내"

EXIT_CODE=0
"$CLAUDE" --model sonnet --dangerously-skip-permissions --print "$PROMPT" >> "$LOG_FILE" 2>&1 || EXIT_CODE=$?

# Notion + Telegram (Digest 은 SILENT 목록에 없어서 알림 나감)
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
    bash "$STOCK_DIR/telegram_notify.sh" "$STOCK_DIR/$REPORT_FILE" "Daily Digest" >> "$LOG_FILE" 2>&1 || true
fi

echo "$(date): Daily Digest 종료 (exit=$EXIT_CODE)" | tee -a "$LOG_FILE"
exit $EXIT_CODE
