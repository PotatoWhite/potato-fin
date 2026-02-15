#!/bin/bash
# 자기개선 루프 (Daily Self-Improvement)
# 매일 14:00 KST 실행 — 운영 데이터를 분석하고 시스템을 점진적으로 개선한다.
#
# 운영 루프와 분리:
#   - improve 브랜치에서 작업 → 검증 후 main 머지
#   - 운영(main)은 항상 안정 상태 유지
#   - 개선이 실패해도 운영에 영향 없음
#
# 개선 범위:
#   1. 보고서 프롬프트 개선 (run_report.sh 등의 품질 교훈 섹션)
#   2. 검증 로직 강화 (validate_report.py, price_verify.py)
#   3. 알림 임계값 최적화 (alert_config.json)
#   4. 버그 수정 (로그에서 발견된 에러)
#   5. 모니터링 개선 (news_monitor.py 키워드/소스)
#
# 금지 사항:
#   - CLAUDE.md 핵심 구조 변경 금지 (보고서 템플릿 등)
#   - 기존 동작 파괴하는 리팩터링 금지
#   - .env, 매매기록.xlsx 등 사용자 데이터 수정 금지

set -euo pipefail

unset CLAUDECODE 2>/dev/null || true

STOCK_DIR="/home/bravopotato/Spaces/finspace/potato-fin"
PYTHON="$STOCK_DIR/.venv/bin/python3"
CLAUDE="/home/linuxbrew/.linuxbrew/bin/claude"
LOG_DIR="$HOME/logs/stock-monitor"
IMPROVE_LOG="$LOG_DIR/improve_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$LOG_DIR"

echo "$(date): 자기개선 루프 시작" >> "$IMPROVE_LOG"

cd "$STOCK_DIR"

# ── 1단계: 개선 데이터 수집 ──
echo "$(date): 개선 데이터 수집" >> "$IMPROVE_LOG"
IMPROVE_DATA=$("$PYTHON" "$STOCK_DIR/collect_improvement_data.py" 2>/dev/null || echo "데이터 수집 실패")
echo "$IMPROVE_DATA" >> "$IMPROVE_LOG"

# ── 2단계: improve 브랜치 준비 ──
echo "$(date): improve 브랜치 준비" >> "$IMPROVE_LOG"
CURRENT_BRANCH=$(git branch --show-current)
IMPROVE_BRANCH="improve/$(date +%Y%m%d)"

# 이전 improve 브랜치가 머지 안 된 채 있으면 삭제
git branch -D "$IMPROVE_BRANCH" 2>/dev/null || true
git checkout -b "$IMPROVE_BRANCH" main >> "$IMPROVE_LOG" 2>&1

# ── 3단계: Claude로 개선 실행 ──
echo "$(date): Claude 개선 세션 시작" >> "$IMPROVE_LOG"
"$CLAUDE" -p "너는 Spud, potato-fin 시스템의 자기개선 에이전트다.
아래 운영 데이터를 분석하고, 시스템을 점진적으로 개선하라.

=== 핵심 원칙 ===
1. 안정성 우선: 기존 동작을 깨뜨리지 않는다
2. 점진적 개선: 한 번에 큰 변경 금지. 작은 개선을 꾸준히
3. 데이터 기반: 감이 아닌 로그/정확도/오차 데이터 기반으로 판단
4. 검증 가능: 개선 전후 비교 가능해야 함

=== 개선 우선순위 (위에서 아래로) ===
1. 에러/버그 수정 — 로그에서 발견된 에러 해결
2. 가격 정확도 — price_verify에서 반복 오차 패턴 발견 시 근본 원인 해결
3. 예측 정확도 — 체계적 편향 보정 (프롬프트 개선, 가중치 조정)
4. 보고서 품질 — 검증 점수 하락 패턴 해결
5. 모니터링 — 뉴스 소스/키워드 최적화
6. 코드 품질 — 중복 제거, 성능 개선 (기능 변경 없을 때만)

=== 수정 가능 파일 ===
- run_report.sh, run_korea_report.sh: 프롬프트 품질 교훈 섹션
- run_premarket.sh, run_midcheck.sh: 프롬프트 개선
- validate_report.py: 검증 로직 강화
- price_verify.py: 가격 검증 개선
- price_alerts.py, alert_config.json: 알림 임계값
- news_monitor.py: 키워드/소스/임계값
- update_thesis.py: 확신도 로직
- portfolio_tracker.py: 추적 로직
- telegram_bot.py: 명령어/응답 개선
- collect_improvement_data.py: 데이터 수집 개선

=== 수정 금지 파일 ===
- CLAUDE.md (보고서 템플릿 구조)
- .env, 매매기록.xlsx, 주식.xlsx
- 주가_업데이트.py, market_data.py, technical_analysis.py (핵심 데이터 수집)
- mcp_server.py

=== 작업 절차 ===
1. 아래 운영 데이터를 분석하여 개선 포인트 3개 이내로 선정
2. 각 개선의 근거(데이터), 변경 내용, 예상 효과를 설명
3. 코드 변경 실행 (Edit/Write)
4. 변경 후 간단한 검증 (python -c 또는 bash로 syntax 체크)
5. 변경 사항을 git commit (메시지에 개선 근거 포함)

=== 운영 데이터 ===
$IMPROVE_DATA" \
    --allowedTools "Read,Edit,Write,Bash,Glob,Grep" \
    --permission-mode bypassPermissions \
    --model sonnet \
    --max-budget-usd 2.0 \
    >> "$IMPROVE_LOG" 2>&1
IMPROVE_EXIT=$?

echo "$(date): 개선 세션 완료 (exit=$IMPROVE_EXIT)" >> "$IMPROVE_LOG"

# ── 4단계: 검증 ──
echo "$(date): 개선 검증" >> "$IMPROVE_LOG"
VERIFY_PASS=true

# Python 문법 체크
for pyfile in validate_report.py price_verify.py price_alerts.py news_monitor.py \
              update_thesis.py portfolio_tracker.py telegram_bot.py collect_improvement_data.py; do
    if [[ -f "$STOCK_DIR/$pyfile" ]]; then
        if ! "$PYTHON" -m py_compile "$STOCK_DIR/$pyfile" >> "$IMPROVE_LOG" 2>&1; then
            echo "$(date): ❌ 문법 에러: $pyfile" >> "$IMPROVE_LOG"
            VERIFY_PASS=false
        fi
    fi
done

# Shell 문법 체크
for shfile in run_report.sh run_korea_report.sh run_premarket.sh run_midcheck.sh; do
    if [[ -f "$STOCK_DIR/$shfile" ]]; then
        if ! bash -n "$STOCK_DIR/$shfile" >> "$IMPROVE_LOG" 2>&1; then
            echo "$(date): ❌ 문법 에러: $shfile" >> "$IMPROVE_LOG"
            VERIFY_PASS=false
        fi
    fi
done

# ── 5단계: main 머지 또는 롤백 ──
if [[ "$VERIFY_PASS" == true && $IMPROVE_EXIT -eq 0 ]]; then
    # 변경사항이 있는지 확인
    if git diff --quiet HEAD main 2>/dev/null; then
        echo "$(date): 변경사항 없음 — 브랜치 삭제" >> "$IMPROVE_LOG"
        git checkout main >> "$IMPROVE_LOG" 2>&1
        git branch -D "$IMPROVE_BRANCH" >> "$IMPROVE_LOG" 2>&1
    else
        echo "$(date): ✅ 검증 통과 — main 머지" >> "$IMPROVE_LOG"
        git checkout main >> "$IMPROVE_LOG" 2>&1
        git merge "$IMPROVE_BRANCH" --no-edit >> "$IMPROVE_LOG" 2>&1
        git branch -d "$IMPROVE_BRANCH" >> "$IMPROVE_LOG" 2>&1
        echo "$(date): main 머지 완료" >> "$IMPROVE_LOG"
    fi
else
    echo "$(date): ❌ 검증 실패 — 롤백" >> "$IMPROVE_LOG"
    git checkout main >> "$IMPROVE_LOG" 2>&1
    git branch -D "$IMPROVE_BRANCH" >> "$IMPROVE_LOG" 2>&1
    echo "$(date): improve 브랜치 삭제, main 복귀" >> "$IMPROVE_LOG"
fi

# ── 정리 ──
find "$LOG_DIR" -name "improve_*.log" -mtime +30 -delete 2>/dev/null || true

echo "$(date): 자기개선 루프 종료" >> "$IMPROVE_LOG"
