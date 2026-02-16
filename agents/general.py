"""
일반 대화 에이전트 — Claude Haiku 기반 Q&A

금융/메모/할일 외의 일반 대화를 처리.
"""

import os
import subprocess
from pathlib import Path

from agents import BaseAgent, register_agent

STOCK_DIR = Path(__file__).resolve().parent.parent
CLAUDE_PATH = "/home/linuxbrew/.linuxbrew/bin/claude"


class GeneralAgent(BaseAgent):
    name = 'general'
    description = '일반 대화/Q&A'
    emoji = '💬'

    def handle(self, text: str, chat_id: str, context: dict) -> str:
        # 대화 이력 구성
        conversations = context.get('conversation', [])
        history_lines = []
        for m in conversations[-6:]:
            role = '사용자' if m.get('role') == 'user' else '비서'
            history_lines.append(f"{role}: {m.get('content', '')}")
        history = '\n'.join(history_lines)

        prompt = f"""당신은 사용자의 개인 비서다.
텔레그램으로 자연스럽게 대화한다.

최근 대화:
{history}

사용자: {text}

규칙:
- 텔레그램이므로 3000자 이내, 핵심 위주로 답하라
- 친근하고 도움이 되는 톤으로 답하라
- 반말/존댓말은 사용자의 톤에 맞춰라
- 한국어로 답하라
- 모르는 것은 솔직히 모른다고 하라"""

        try:
            result = subprocess.run(
                [CLAUDE_PATH, '-p', prompt,
                 '--model', 'haiku',
                 '--max-budget-usd', '0.10',
                 '--allowedTools', '',
                 '--permission-mode', 'bypassPermissions'],
                capture_output=True, text=True, timeout=30,
                cwd=str(STOCK_DIR),
                env={**os.environ, 'CLAUDECODE': ''}
            )
            response = result.stdout.strip()
            if response:
                return response[:3000]
            if result.stderr:
                return f"처리 중 오류: {result.stderr[:200]}"
            return "답을 생성하지 못했습니다. 다시 시도해 주세요."
        except subprocess.TimeoutExpired:
            return "응답 시간 초과. 다시 시도해 주세요."
        except Exception as e:
            return f"처리 실패: {e}"

    def get_help(self) -> str:
        return """💬 *일반 대화*
아무 말이나 하세요!
인사, 질문, 잡담 모두 OK."""


general_agent = GeneralAgent()
register_agent(general_agent)
