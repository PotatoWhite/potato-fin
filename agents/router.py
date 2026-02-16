"""
3단계 메시지 라우팅

Tier 1: 키워드 매칭 (~40개 패턴, 즉시)
Tier 2: Claude Haiku 분류 (미매칭 시, 2~5초)
"""

import os
import subprocess
from pathlib import Path

STOCK_DIR = Path(__file__).resolve().parent.parent
CLAUDE_PATH = "/home/linuxbrew/.linuxbrew/bin/claude"

# Tier 1 키워드 → 에이전트 매핑
KEYWORD_MAP = {
    'finance': [
        '주식', '종목', '포트폴리오', '보고서', '시세', '가격', '어때', '어떄', '어떻',
        '테제', '손절', '감시', '정확도', '예측', '업데이트', '매수', '매도',
        '배당', '실적', '차트', '스냅샷', '알림', '알럿', '모니터', '회고', '검증',
        '리포트', '총액', '평가', '자산', '전종목',
    ],
    'execute': [
        '보고서 만들', '리포트 만들', '업데이트해', '업뎃해', '갱신해',
        '장전 브리핑', '장중 체크', '프리마켓', '미드체크',
        '감시 실행', '알림 실행', '알림 체크',
    ],
    'develop': [
        '코드 개선', '코드 수정', '코드 변경', '코드 고쳐', '코드 바꿔',
        '기능 추가해', '버그 수정', '리팩토', '최적화해', '개발해',
        '스크립트 수정', '스크립트 개선', '파일 수정',
    ],
    'memo': [
        '메모', '기억해', '적어', '노트', '저장해', '메모 보여', '메모 삭제',
        '기록해', '적어둬', '메모해',
    ],
    'todo': [
        '할일', '할 일', 'todo', '해야할', '체크리스트', '할일 추가',
        '할 거', '해야 할', '할일 목록', '할일 완료',
    ],
    'calendar': [
        '리마인더', '일정', '스케줄',
        '분 후에', '시간 후에', '시에 알려', '분 후 알려',
        '내일 알려', '모레 알려', '매일 알려', '매주 알려',
        '후에 알려', '뒤에 알려',
    ],
    'search': [
        '검색해', '찾아봐', '알아봐', '조사해', '최신 뉴스',
        '검색', '찾아줘', '알아봐줘',
    ],
    'travel': [
        '여행', '항공', '호텔', '비행기', '숙소', '관광', '비자',
        '환전', '패킹', '짐싸기', '일정 짜', '여행지', '투어',
        '여행 일정',
    ],
}

# execute/develop는 finance 에이전트에서 처리하므로 finance로 라우팅
AGENT_ALIAS = {
    'execute': 'finance',
    'develop': 'develop',
}


def route_by_keyword(text: str) -> str | None:
    """Tier 1: 키워드 매칭. 에이전트 이름 반환. 미매칭 시 None."""
    low = text.lower().strip()

    # execute가 가장 구체적이므로 먼저 검사
    for kw in KEYWORD_MAP['execute']:
        if kw in low:
            return 'finance'

    # develop 다음
    for kw in KEYWORD_MAP['develop']:
        if kw in low:
            return 'develop'

    # 나머지 에이전트 (구체적 → 일반적 순서로 검사)
    check_order = ['memo', 'todo', 'calendar', 'travel', 'search', 'finance']

    # 모든 에이전트의 키워드를 길이순 정렬 후 스캔 (긴 키워드=더 구체적 우선)
    all_keywords = []
    for agent in check_order:
        for kw in KEYWORD_MAP.get(agent, []):
            all_keywords.append((len(kw), kw, agent))
    all_keywords.sort(key=lambda x: x[0], reverse=True)  # 긴 키워드 먼저
    for _, kw, agent in all_keywords:
        if kw in low:
            return AGENT_ALIAS.get(agent, agent)

    return None


def route_by_haiku(text: str) -> str:
    """Tier 2: Claude Haiku 분류. 에이전트 이름 반환."""
    prompt = f"""사용자 메시지를 아래 카테고리 중 하나로 분류하라. 카테고리 이름만 답하라:
FINANCE - 주식/투자/경제/포트폴리오/시장/환율
MEMO - 메모/기억/저장/기록
TODO - 할일/작업/체크리스트
CALENDAR - 리마인더/일정/알림/타이머
SEARCH - 웹검색/조사/뉴스/정보 조회
TRAVEL - 여행/관광/항공/숙소/비자
DEVELOP - 코드/프로그래밍/개선/수정/버그
GENERAL - 일반 대화/잡담/인사/질문/기타

메시지: {text}
분류:"""

    try:
        result = subprocess.run(
            [CLAUDE_PATH, '-p', prompt, '--model', 'haiku',
             '--max-budget-usd', '0.01', '--allowedTools', ''],
            capture_output=True, text=True, timeout=15,
            cwd=str(STOCK_DIR),
            env={**os.environ, 'CLAUDECODE': ''}
        )
        category = result.stdout.strip().split('\n')[0].strip().upper()
        mapping = {
            'FINANCE': 'finance',
            'MEMO': 'memo',
            'TODO': 'todo',
            'CALENDAR': 'calendar',
            'SEARCH': 'search',
            'TRAVEL': 'travel',
            'DEVELOP': 'develop',
            'GENERAL': 'general',
        }
        return mapping.get(category, 'general')
    except Exception:
        return 'general'


def route(text: str, context: dict = None) -> str:
    """3단계 라우팅. 에이전트 이름 반환."""
    # "그거 메모해" 등 크로스 에이전트 패턴
    cross_patterns = {
        'memo': ['그거 메모', '그거 저장', '그거 기억', '그거 적어', '방금 거 메모', '위에 거 메모'],
        'todo': ['그거 할일', '그거 추가'],
    }
    low = text.lower().strip()
    for agent, patterns in cross_patterns.items():
        for p in patterns:
            if p in low:
                return agent

    # Tier 1: 키워드 매칭
    agent = route_by_keyword(text)
    if agent:
        return agent

    # Tier 2: Claude Haiku 분류
    return route_by_haiku(text)
