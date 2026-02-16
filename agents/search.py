"""
웹 검색 에이전트 — Claude Haiku + WebSearch

사용자 질문에 대해 웹 검색 후 한국어로 답변.
"""

import os
import subprocess
from pathlib import Path

from agents import BaseAgent, register_agent

STOCK_DIR = Path(__file__).resolve().parent.parent
CLAUDE_PATH = "/home/linuxbrew/.linuxbrew/bin/claude"


class SearchAgent(BaseAgent):
    name = 'search'
    description = '웹 검색/리서치'
    emoji = '🔍'

    def handle(self, text: str, chat_id: str, context: dict) -> str:
        # 검색 키워드 정리
        query = text
        for prefix in ['검색해', '검색', '찾아봐', '찾아줘', '알아봐', '알아봐줘',
                        '조사해', '검색:', '찾아:']:
            if query.lower().startswith(prefix):
                query = query[len(prefix):].strip()
                break
        query = query.lstrip('-:').strip()

        if not query or len(query) < 2:
            return "검색할 내용을 입력해 주세요.\n예: 검색 트럼프 관세 최신"

        try:
            result = subprocess.run(
                [CLAUDE_PATH, '-p',
                 f'다음 질문에 대해 웹 검색 후 한국어로 3000자 이내 답하라. 핵심 위주로 구조적으로 정리하라: {query}',
                 '--model', 'haiku',
                 '--max-budget-usd', '0.50',
                 '--allowedTools', 'WebSearch,WebFetch',
                 '--permission-mode', 'bypassPermissions'],
                capture_output=True, text=True, timeout=60,
                cwd=str(STOCK_DIR),
                env={**os.environ, 'CLAUDECODE': ''}
            )
            response = result.stdout.strip()
            if response:
                return response[:3000]
            return "검색 결과를 가져오지 못했습니다."
        except subprocess.TimeoutExpired:
            return "검색 시간 초과. 다시 시도해 주세요."
        except Exception as e:
            return f"검색 실패: {e}"

    def handle_command(self, args: str, chat_id: str, context: dict) -> str:
        if not args.strip():
            return "검색할 내용을 입력해 주세요.\n예: /search 트럼프 관세 최신"
        return self.handle(args, chat_id, context)

    def get_help(self) -> str:
        return """🔍 *검색 에이전트*
/search 트럼프 관세 — 웹 검색
"검색해 파이썬 async" — 웹 검색
"최신 뉴스 알려줘" — 뉴스 검색"""


search_agent = SearchAgent()
register_agent(search_agent)
