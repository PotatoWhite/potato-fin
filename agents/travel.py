"""
여행 도우미 에이전트 — Claude + WebSearch + 환율 데이터

여행 계획/정보/항공편/숙소/비자/환전 등.
"""

import os
import subprocess
from pathlib import Path

from agents import BaseAgent, register_agent

STOCK_DIR = Path(__file__).resolve().parent.parent
CLAUDE_PATH = "/home/linuxbrew/.linuxbrew/bin/claude"


def get_fx_rates() -> str:
    """현재 환율 정보 (yfinance)."""
    try:
        import yfinance as yf
        pairs = ['USDKRW=X', 'JPYKRW=X', 'EURKRW=X', 'THBKRW=X']
        data = yf.download(pairs, period='1d', progress=False, group_by='ticker')
        lines = []
        labels = {
            'USDKRW=X': 'USD/KRW', 'JPYKRW=X': 'JPY/KRW(100엔)',
            'EURKRW=X': 'EUR/KRW', 'THBKRW=X': 'THB/KRW',
        }
        for pair in pairs:
            try:
                close = data[pair]['Close'].dropna()
                if len(close) > 0:
                    rate = float(close.iloc[-1])
                    label = labels.get(pair, pair)
                    if 'JPY' in pair:
                        lines.append(f"{label}: ₩{rate * 100:,.0f}")
                    else:
                        lines.append(f"{label}: ₩{rate:,.0f}")
            except Exception:
                pass
        return ', '.join(lines) if lines else "환율 조회 실패"
    except Exception:
        return "환율 조회 불가"


def is_complex_query(text: str) -> bool:
    """복잡한 여행 질문인지 판단 (Sonnet 사용 여부)."""
    complex_keywords = ['계획', '일정', '코스', '루트', '여행지 추천', '짜줘',
                         '여행 일정', '여행 계획', '비교해', '추천해']
    return any(kw in text.lower() for kw in complex_keywords)


class TravelAgent(BaseAgent):
    name = 'travel'
    description = '여행 계획/정보/항공/숙소'
    emoji = '✈️'

    def handle(self, text: str, chat_id: str, context: dict) -> str:
        fx_info = get_fx_rates()
        model = 'sonnet' if is_complex_query(text) else 'haiku'
        budget = '1.00' if model == 'sonnet' else '0.50'
        timeout = 90 if model == 'sonnet' else 60

        prompt = f"""당신은 여행 전문가다. 사용자의 여행 관련 질문에 답하라.
현재 환율: {fx_info}
웹 검색으로 최신 정보를 확인하라.
3000자 이내 한국어로 답하라.
구체적인 가격, 시간, 링크를 포함하라.

질문: {text}"""

        try:
            result = subprocess.run(
                [CLAUDE_PATH, '-p', prompt, '--model', model,
                 '--max-budget-usd', budget,
                 '--allowedTools', 'WebSearch,WebFetch',
                 '--permission-mode', 'bypassPermissions'],
                capture_output=True, text=True, timeout=timeout,
                cwd=str(STOCK_DIR),
                env={**os.environ, 'CLAUDECODE': ''}
            )
            response = result.stdout.strip()
            if response:
                return response[:3000]
            return "답변을 생성하지 못했습니다."
        except subprocess.TimeoutExpired:
            return "응답 시간 초과. 다시 시도해 주세요."
        except Exception as e:
            return f"처리 실패: {e}"

    def handle_command(self, args: str, chat_id: str, context: dict) -> str:
        if not args.strip():
            return "여행 관련 질문을 입력해 주세요.\n예: /travel 도쿄 3박4일 일정"
        return self.handle(args, chat_id, context)

    def get_help(self) -> str:
        return """✈️ *여행 에이전트*
/travel 도쿄 3박4일 — 여행 계획
"방콕 비자 필요해?" — 비자 정보
"환전 얼마나?" — 환율 + 추천"""


travel_agent = TravelAgent()
register_agent(travel_agent)
