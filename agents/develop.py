"""
코드 개선 에이전트 — Claude Sonnet with tools (백그라운드)

기존 telegram_bot.py의 handle_develop() 로직.
"""

import os
import subprocess
import threading
from pathlib import Path

from agents import BaseAgent, register_agent

STOCK_DIR = Path(__file__).resolve().parent.parent
CLAUDE_PATH = "/home/linuxbrew/.linuxbrew/bin/claude"


class DevelopAgent(BaseAgent):
    name = 'develop'
    description = '코드 개선/수정/버그 수정'
    emoji = '🔧'

    def handle(self, text: str, chat_id: str, context: dict) -> str:
        send_fn = context.get('send_fn')
        if send_fn:
            send_fn(f"🔧 작업 분석 중...\n\"{text}\"", chat_id)

        prompt = f"""사용자가 텔레그램으로 다음 지시를 내렸다:
"{text}"

작업 디렉토리: {STOCK_DIR}
먼저 CLAUDE.md를 읽고 프로젝트 구조를 파악하라.
지시를 수행하라. 결과를 간결하게 요약하라 (텔레그램 메시지용, 3000자 이내):
1. 무엇을 변경했는지 (파일명 + 변경 내용)
2. 왜 변경했는지
3. 테스트 결과

주의:
- git push, rm -rf, git reset --hard 등 파괴적 명령 금지
- git commit은 하지 말 것 (사용자가 확인 후 결정)
- 기존 기능을 깨뜨리지 말 것
- 실행 중인 서비스(systemd, cron)에 영향을 주지 말 것"""

        def _run():
            try:
                result = subprocess.run(
                    [CLAUDE_PATH, '-p', prompt,
                     '--model', 'sonnet',
                     '--max-budget-usd', '5',
                     '--permission-mode', 'bypassPermissions'],
                    capture_output=True, text=True, timeout=300,
                    cwd=str(STOCK_DIR),
                    env={**os.environ, 'CLAUDECODE': ''}
                )
                response = result.stdout.strip()
                if response:
                    if len(response) > 3500:
                        response = response[:3500] + "\n\n... (truncated)"
                    if send_fn:
                        send_fn(f"✅ 작업 완료\n\n{response}", chat_id)
                else:
                    err = result.stderr.strip()[:500] if result.stderr else "출력 없음"
                    if send_fn:
                        send_fn(f"⚠️ 완료 (출력 없음)\n{err}", chat_id)
            except subprocess.TimeoutExpired:
                if send_fn:
                    send_fn("⏰ 작업 시간 초과 (5분).", chat_id)
            except Exception as e:
                if send_fn:
                    send_fn(f"❌ 작업 실패: {e}", chat_id)

        threading.Thread(target=_run, daemon=True).start()
        return ''  # 백그라운드 실행, 응답은 비동기

    def get_help(self) -> str:
        return """🔧 *개발 에이전트*
"XX 개선해" — 코드 분석 + 자동 수정
"XX 추가해" — 기능 구현
"XX 수정해" — 버그 수정
(Claude Sonnet, $5 이내)"""


develop_agent = DevelopAgent()
register_agent(develop_agent)
