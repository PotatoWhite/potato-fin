#!/usr/bin/env bash
# Coordinator helpers for potato-team session.
# Source this in the coord pane: `source coord-functions.sh`

POTATO_TEAM_SESSION="${POTATO_TEAM_SESSION:-potato-team}"

# zsh + bash 호환: case 로 매핑 (배열 인덱싱 문법 차이 회피)
_potato_team_pane_index() {
  case "$1" in
    pm)        echo 1; return 0 ;;
    quant)     echo 2; return 0 ;;
    architect) echo 3; return 0 ;;
    devil)     echo 4; return 0 ;;
    trader)    echo 5; return 0 ;;
    *)         return 1 ;;
  esac
}

_potato_team_label() {
  case "$1" in
    1) echo "민지(PM)" ;;
    2) echo "현우(퀀트)" ;;
    3) echo "지훈(아키텍트)" ;;
    4) echo "수아(악마)" ;;
    5) echo "태경(트레이더)" ;;
  esac
}

# ask "질문" — broadcast to all 5 persona panes
# claude TUI가 긴 입력을 paste-mode로 처리하므로 텍스트와 Enter를 분리해서 전송
ask() {
  local q="$*"
  if [ -z "$q" ]; then
    echo "Usage: ask \"질문\""
    return 1
  fi
  local i
  # 1단계: 5명 모두에게 텍스트 전송
  for i in 1 2 3 4 5; do
    tmux send-keys -t "${POTATO_TEAM_SESSION}:0.${i}" -- "$q"
  done
  # 2단계: paste-mode 해제 대기 후 Enter로 submit
  sleep 0.3
  for i in 1 2 3 4 5; do
    tmux send-keys -t "${POTATO_TEAM_SESSION}:0.${i}" Enter
  done
  echo "📢 5명에게 broadcast 전송: $q"
}

# ask1 persona "질문" — send to one persona only
ask1() {
  local who="$1"; shift
  local q="$*"
  if [ -z "$who" ] || [ -z "$q" ]; then
    echo "Usage: ask1 <pm|quant|architect|devil|trader> \"질문\""
    return 1
  fi
  local idx
  if ! idx=$(_potato_team_pane_index "$who"); then
    echo "알 수 없는 페르소나: $who (pm|quant|architect|devil|trader)"
    return 1
  fi
  tmux send-keys -t "${POTATO_TEAM_SESSION}:0.${idx}" -- "$q"
  sleep 0.3
  tmux send-keys -t "${POTATO_TEAM_SESSION}:0.${idx}" Enter
  echo "🎯 $(_potato_team_label "$idx")에게 전송: $q"
}

# focus persona — switch focus to that persona's pane
focus() {
  local who="$1"
  local idx
  if ! idx=$(_potato_team_pane_index "$who"); then
    echo "알 수 없는 페르소나: $who (pm|quant|architect|devil|trader)"
    return 1
  fi
  tmux select-pane -t "${POTATO_TEAM_SESSION}:0.${idx}"
}

# clear-all — clear all 5 persona contexts via /clear
clear-all() {
  local i
  for i in 1 2 3 4 5; do
    tmux send-keys -t "${POTATO_TEAM_SESSION}:0.${i}" -- "/clear"
  done
  sleep 0.3
  for i in 1 2 3 4 5; do
    tmux send-keys -t "${POTATO_TEAM_SESSION}:0.${i}" Enter
  done
  echo "🧹 5명 컨텍스트 초기화"
}

# round "질문" — broadcast then prompt user to read responses
round() {
  ask "$@"
  echo ""
  echo "⏳ 5명 응답 대기 중. Ctrl-b 화살표로 pane 이동, Ctrl-b z로 확대."
  echo "   다 읽었으면 종합 의견 적고 다음 ask/round 진행."
}

team-help() {
  cat <<'EOF'

╔══════════════════════════════════════════════════════════════╗
║                potato-team coordinator pane                  ║
╚══════════════════════════════════════════════════════════════╝

📢 ask "질문"               5명 전부에게 broadcast
🎯 ask1 pm "질문"           1명에게만 (pm/quant/architect/devil/trader)
🔁 round "질문"             broadcast + 응답 대기 안내
👀 focus quant              해당 pane으로 포커스 이동
🧹 clear-all                5명 컨텍스트 초기화 (/clear)
❓ team-help                이 도움말 다시 보기

페르소나 5명:
  pm        민지   제품책임자     "그게 어떤 결정을 바꿔?"
  quant     현우   퀀트          "수치는?"
  architect 지훈   아키텍트       "이게 어떻게 죽는가?"
  devil     수아   악마          "S&P 대비 알파는?"
  trader    태경   트레이더       "max drawdown은?"

tmux 단축키:
  Ctrl-b 화살표           pane 이동
  Ctrl-b z                현재 pane 확대/축소 (다시 z 누르면 복귀)
  Ctrl-b d                detach (세션 살려두고 빠져나옴)
  Ctrl-b [                스크롤백 모드 (q로 종료)

세션 종료:
  tmux kill-session -t potato-team

EOF
}
