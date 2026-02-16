"""
에이전트 프레임워크 — 베이스 클래스 + 레지스트리

각 에이전트는 BaseAgent를 상속하고 handle() + get_help()을 구현한다.
"""


class BaseAgent:
    """모든 에이전트의 베이스 클래스."""

    name: str = 'base'
    description: str = ''
    emoji: str = ''

    def handle(self, text: str, chat_id: str, context: dict) -> str:
        """메시지 처리 → 응답 문자열 반환."""
        raise NotImplementedError

    def handle_command(self, args: str, chat_id: str, context: dict) -> str:
        """슬래시 명령어 처리 → 응답 문자열 반환."""
        return self.handle(args, chat_id, context)

    def get_help(self) -> str:
        """이 에이전트의 사용법 반환."""
        return f"{self.emoji} {self.name}: {self.description}"


# 에이전트 레지스트리 (import 시 자동 등록)
AGENTS: dict[str, BaseAgent] = {}


def register_agent(agent: BaseAgent):
    """에이전트를 레지스트리에 등록."""
    AGENTS[agent.name] = agent
    return agent
