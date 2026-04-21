#!/usr/bin/env bash
# 5명 페르소나의 마지막 응답을 뽑아서 한 파일에 합친다.
# 사용: ./team/collect.sh [출력파일]
# 기본 출력: team/briefs/YYYY-MM-DD_HHMM.md

set -euo pipefail

SESSION="${POTATO_TEAM_SESSION:-potato-team}"
TEAM_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$TEAM_DIR/briefs/$(date +%Y-%m-%d_%H%M).md}"

mkdir -p "$(dirname "$OUT")"

LABELS=("민지(PM)" "현우(퀀트)" "지훈(아키텍트)" "수아(악마)" "태경(트레이더)")

{
  echo "# potato-team 진단 리포트"
  echo ""
  echo "- 수집 시각: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "- 세션: \`$SESSION\`"
  echo ""
  echo "---"
  echo ""

  for i in 0 1 2 3 4; do
    p=$((i + 1))
    label="${LABELS[$i]}"
    echo "## ${label}"
    echo ""
    echo '```'
    # pane의 scrollback 포함 전체 캡처 → 마지막 ● 응답 블록 추출
    tmux capture-pane -t "${SESSION}:0.${p}" -p -S -2000 \
      | sed -n '/^❯ \/home\/bravopotato/,$p' \
      | grep -v '^──' \
      | grep -v 'esc to interrupt' \
      | grep -v '? for shortcuts' \
      | grep -v '^❯ $' \
      | sed '/^$/N;/^\n$/d'
    echo '```'
    echo ""
  done
} > "$OUT"

echo "✅ 수집 완료: $OUT"
echo ""
echo "미리보기:"
head -40 "$OUT"
