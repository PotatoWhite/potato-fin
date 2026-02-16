"""
메모 에이전트 — 메모 저장/검색/삭제

CRUD + 검색 + 크로스 에이전트 (직전 응답 저장).
"""

import re

from agents import BaseAgent, register_agent
from assistant_db import add_memo, list_memos, search_memos, delete_memo, pin_memo


# 카테고리 키워드 매핑
CATEGORY_KEYWORDS = {
    'important': ['중요', '핵심', '필수'],
    'idea': ['아이디어', '생각', '구상'],
    'shopping': ['장보기', '쇼핑', '구매', '사야할'],
    'work': ['업무', '회사', '일'],
    'finance': ['투자', '주식', '종목', '매수', '매도'],
}


def detect_category(text: str) -> str:
    low = text.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in low:
                return cat
    return 'general'


def extract_tags(text: str) -> str:
    tags = re.findall(r'#(\S+)', text)
    return ','.join(tags) if tags else ''


class MemoAgent(BaseAgent):
    name = 'memo'
    description = '메모 저장/검색/삭제'
    emoji = '📝'

    def handle(self, text: str, chat_id: str, context: dict) -> str:
        low = text.lower().strip()

        # 크로스 에이전트: "그거 메모해" → 직전 응답 저장
        cross_patterns = ['그거 메모', '그거 저장', '그거 기억', '그거 적어',
                          '방금 거 메모', '위에 거 메모', '그거 기록']
        for p in cross_patterns:
            if p in low:
                last = context.get('last_response', '')
                if last:
                    mid = add_memo(last[:500], category='general')
                    return f"📝 직전 응답을 메모 #{mid}에 저장했습니다."
                return "저장할 직전 응답이 없습니다."

        # 메모 삭제
        m = re.search(r'(?:메모|노트)\s*(?:#?\s*)?(\d+)\s*(?:번?\s*)?삭제', low)
        if m:
            mid = int(m.group(1))
            if delete_memo(mid):
                return f"🗑 메모 #{mid} 삭제 완료"
            return f"메모 #{mid}을 찾을 수 없습니다."

        # 메모 고정
        m = re.search(r'(?:메모|노트)\s*(?:#?\s*)?(\d+)\s*(?:번?\s*)?고정', low)
        if m:
            mid = int(m.group(1))
            if pin_memo(mid, True):
                return f"📌 메모 #{mid} 고정 완료"
            return f"메모 #{mid}을 찾을 수 없습니다."

        # 메모 검색
        m = re.search(r'(?:메모|노트)\s*(?:검색|찾기?)\s+(.+)', low)
        if m:
            query = m.group(1).strip()
            results = search_memos(query)
            if not results:
                return f"'{query}' 관련 메모가 없습니다."
            return self._format_list(results, f"'{query}' 검색 결과")

        # 메모 목록 (카테고리별)
        if any(kw in low for kw in ['메모 보여', '메모 목록', '메모 전체', '노트 보여', '메모 리스트']):
            # 카테고리 지정 확인
            category = None
            for cat, kws in CATEGORY_KEYWORDS.items():
                if any(kw in low for kw in kws):
                    category = cat
                    break
            memos = list_memos(category=category, limit=15)
            if not memos:
                return "저장된 메모가 없습니다."
            title = f"{category} 메모" if category else "전체 메모"
            return self._format_list(memos, title)

        # 메모 저장 (기본)
        # 키워드를 제거하고 내용 추출 (접두사/접미사 모두 처리)
        content = text
        memo_keywords = ['메모해줘', '메모해', '메모 해', '기억해줘', '기억해', '기억 해',
                         '적어줘', '적어둬', '적어', '저장해줘', '저장해', '저장 해',
                         '기록해줘', '기록해', '메모:', '노트:', '메모', '노트']
        for kw in memo_keywords:
            if low.startswith(kw):
                content = text[len(kw):].strip()
                break
            if low.endswith(kw):
                content = text[:len(text) - len(kw)].strip()
                break
            # 중간에 있는 경우: 앞부분을 content로 (접미사 패턴)
            if kw in low:
                idx = low.index(kw)
                before = text[:idx].strip()
                after = text[idx + len(kw):].strip()
                # 앞이 더 길면 앞이 내용 ("내일 회의 메모해")
                # 뒤가 더 길면 뒤가 내용 ("메모해 내일 회의")
                content = before if len(before) >= len(after) else after
                if content:
                    break

        # "-" 또는 ":" 로 시작하면 제거
        content = content.lstrip('-:').strip()

        if not content or len(content) < 2:
            return "메모할 내용을 입력해 주세요.\n예: 메모해 내일 회의 10시"

        category = detect_category(content)
        tags = extract_tags(content)
        mid = add_memo(content, category=category, tags=tags)
        cat_emoji = {'important': '❗', 'idea': '💡', 'shopping': '🛒',
                     'work': '💼', 'finance': '💰'}.get(category, '📝')
        return f"{cat_emoji} 메모 #{mid} 저장 완료 [{category}]"

    def handle_command(self, args: str, chat_id: str, context: dict) -> str:
        """슬래시 명령 /memo 처리."""
        if not args.strip():
            memos = list_memos(limit=10)
            if not memos:
                return "저장된 메모가 없습니다."
            return self._format_list(memos, "최근 메모")
        return self.handle(args, chat_id, context)

    def _format_list(self, memos: list[dict], title: str) -> str:
        lines = [f"📝 *{title}* ({len(memos)}건)", ""]
        for m in memos:
            pin = "📌 " if m.get('pinned') else ""
            cat = m.get('category', '')
            content = m['content'][:80]
            date = m.get('created_at', '')[:10]
            lines.append(f"  {pin}#{m['id']} [{cat}] {content}")
            if date:
                lines.append(f"    _{date}_")
        return '\n'.join(lines)

    def get_help(self) -> str:
        return """📝 *메모 에이전트*
/memo — 최근 메모 목록
"메모해 내일 회의 10시" — 저장
"메모 보여줘" — 전체 목록
"메모 검색 회의" — 검색
"메모 3 삭제" — 삭제
"그거 메모해" — 직전 응답 저장"""


memo_agent = MemoAgent()
register_agent(memo_agent)
