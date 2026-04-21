#!/usr/bin/env bash
# potato-team harness — 5명 페르소나 + coordinator pane을 tmux로 띄움
# 사용: ./team/team-up.sh

set -euo pipefail

SESSION="potato-team"
TEAM_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$TEAM_DIR/.." && pwd)"
MODEL_ALIAS="opus"  # 항상 최신 Opus 가리킴 (현재 4.7)

PERSONAS=(pm quant architect devil trader)
LABELS=("민지(PM)" "현우(퀀트)" "지훈(아키텍트)" "수아(악마)" "태경(트레이더)")

# --- 사전 체크 ---
command -v tmux >/dev/null 2>&1 || { echo "ERROR: tmux 없음" >&2; exit 1; }
CLAUDE_BIN="$(command -v claude || echo /home/bravopotato/.npm-global/bin/claude)"
[ -x "$CLAUDE_BIN" ] || { echo "ERROR: claude CLI 없음 ($CLAUDE_BIN)" >&2; exit 1; }

for p in "${PERSONAS[@]}"; do
  [ -f "$TEAM_DIR/personas/$p.md" ] || { echo "ERROR: $TEAM_DIR/personas/$p.md 없음" >&2; exit 1; }
done

# --- 기존 세션 처리 ---
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "기존 세션 '$SESSION' 발견. 종료 후 재생성..."
  tmux kill-session -t "$SESSION"
fi

# --- 세션 생성 (coordinator pane = 0.0) ---
tmux new-session -d -s "$SESSION" -c "$PROJECT_DIR" -x 240 -y 60
tmux rename-window -t "$SESSION:0" "team"

# pane border 위에 페르소나 이름 표시
tmux set-option -t "$SESSION" pane-border-status top
tmux set-option -t "$SESSION" pane-border-format " #{pane_title} "

# coord pane 라벨
tmux select-pane -t "$SESSION:0.0" -T "🎯 coord (you)"

# --- 오른쪽에 5개 pane 만들기 (vertical stack) ---
# 1) 가로로 split → 오른쪽 pane = 0.1
tmux split-window -h -t "$SESSION:0.0" -c "$PROJECT_DIR"
# 2~5) 0.1을 4번 세로 split → 0.2 0.3 0.4 0.5
for i in 1 2 3 4; do
  tmux split-window -v -t "$SESSION:0.${i}" -c "$PROJECT_DIR"
done

# main-vertical 레이아웃 (왼쪽 큰 pane + 오른쪽 stack)
tmux select-layout -t "$SESSION:0" main-vertical

# 왼쪽 coord pane을 60%로 키우기
TOTAL_W=$(tmux display-message -t "$SESSION:0" -p '#{window_width}')
LEFT_W=$(( TOTAL_W * 60 / 100 ))
tmux resize-pane -t "$SESSION:0.0" -x "$LEFT_W"

# --- 각 페르소나 pane에 claude 실행 ---
for i in "${!PERSONAS[@]}"; do
  pane=$((i + 1))
  persona="${PERSONAS[$i]}"
  label="${LABELS[$i]}"
  prompt_file="$TEAM_DIR/personas/$persona.md"

  tmux select-pane -t "$SESSION:0.${pane}" -T "$label"

  # $(cat ...) expansion은 pane 셸에서 실행되도록 escape
  tmux send-keys -t "$SESSION:0.${pane}" \
    "clear; $CLAUDE_BIN --model $MODEL_ALIAS --name '$label' --append-system-prompt \"\$(cat '$prompt_file')\"" Enter
done

# --- coord pane에 helper 함수 source ---
tmux send-keys -t "$SESSION:0.0" "source '$TEAM_DIR/coord-functions.sh' && clear && team-help" Enter

echo ""
echo "✅ potato-team 세션 생성 완료"
echo ""
echo "  접속:  tmux attach -t $SESSION"
echo "  종료:  tmux kill-session -t $SESSION"
echo ""
echo "5명이 claude를 시작하는 데 잠시 걸립니다 (각 pane 확인)."
echo ""

# 자동 attach (배경 실행하려면 NO_ATTACH=1 set)
if [ "${NO_ATTACH:-0}" != "1" ]; then
  exec tmux attach -t "$SESSION"
fi
