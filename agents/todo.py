"""
할일 에이전트 — 할일 추가/완료/삭제/목록

우선순위 자동 감지 + 기한 파싱.
"""

import re
from datetime import datetime, timedelta

from agents import BaseAgent, register_agent
from assistant_db import add_todo, list_todos, complete_todo, cancel_todo, delete_todo


def detect_priority(text: str) -> str:
    low = text.lower()
    if any(kw in low for kw in ['긴급', '급한', '급히', '중요', '최우선', 'urgent', '지금']):
        return 'high'
    if any(kw in low for kw in ['나중에', '여유', '천천히', '언젠가']):
        return 'low'
    return 'medium'


def parse_due_date(text: str) -> str | None:
    """자연어에서 기한 추출."""
    now = datetime.now()
    low = text.lower()

    # "오늘까지", "오늘"
    if '오늘' in low:
        return now.strftime('%Y-%m-%d 23:59')

    # "내일까지", "내일"
    if '내일' in low:
        d = now + timedelta(days=1)
        return d.strftime('%Y-%m-%d 23:59')

    # "모레"
    if '모레' in low or '모래' in low:
        d = now + timedelta(days=2)
        return d.strftime('%Y-%m-%d 23:59')

    # "N일 후", "N일 내"
    m = re.search(r'(\d+)일\s*(?:후|내|이내|안에)', low)
    if m:
        d = now + timedelta(days=int(m.group(1)))
        return d.strftime('%Y-%m-%d 23:59')

    # "이번주", "이번 주" (금요일 기준, 당일 포함)
    if '이번주' in low or '이번 주' in low:
        days_until_friday = (4 - now.weekday()) % 7
        # 금요일이면 오늘, 토/일이면 다음 금요일
        d = now + timedelta(days=days_until_friday)
        return d.strftime('%Y-%m-%d 23:59')

    # "다음주", "다음 주"
    if '다음주' in low or '다음 주' in low:
        days_until_friday = (4 - now.weekday()) % 7 + 7
        d = now + timedelta(days=days_until_friday)
        return d.strftime('%Y-%m-%d 23:59')

    # "M/D" 또는 "M월 D일"
    m = re.search(r'(\d{1,2})[/월]\s*(\d{1,2})[일]?', low)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            d = now.replace(month=month, day=day, hour=23, minute=59)
            if d < now:
                d = d.replace(year=d.year + 1)
            return d.strftime('%Y-%m-%d %H:%M')
        except ValueError:
            pass

    return None


def extract_content(text: str) -> str:
    """할일 내용 추출 (키워드/기한/우선순위 제거)."""
    content = text
    # 접두어 제거
    for prefix in ['할일 추가', '할 일 추가', '할일:', '할 일:', 'todo:', 'todo',
                    '할일 추가해', '할일추가']:
        if content.lower().startswith(prefix):
            content = content[len(prefix):].strip()
            break

    # "-" 또는 ":" 제거
    content = content.lstrip('-:').strip()

    # 기한 표현 제거 (내용에서)
    for pattern in [r'오늘까지', r'내일까지', r'모레까지', r'\d+일\s*(?:후|내|이내)',
                    r'이번\s*주까지', r'다음\s*주까지']:
        content = re.sub(pattern, '', content).strip()

    # 우선순위 표현 제거
    for kw in ['긴급', '급한', '급히', '최우선', '나중에', '여유', '천천히']:
        content = content.replace(kw, '').strip()

    return content


class TodoAgent(BaseAgent):
    name = 'todo'
    description = '할일 관리 (추가/완료/삭제/목록)'
    emoji = '✅'

    def handle(self, text: str, chat_id: str, context: dict) -> str:
        low = text.lower().strip()

        # 할일 완료
        m = re.search(r'(?:할일|할 일|todo)\s*(?:#?\s*)?(\d+)\s*(?:번?\s*)?완료', low)
        if m:
            tid = int(m.group(1))
            if complete_todo(tid):
                return f"✅ 할일 #{tid} 완료!"
            return f"할일 #{tid}을 찾을 수 없거나 이미 완료됨"

        # "완료" + 번호
        m = re.search(r'완료\s*(?:#?\s*)?(\d+)', low)
        if m:
            tid = int(m.group(1))
            if complete_todo(tid):
                return f"✅ 할일 #{tid} 완료!"
            return f"할일 #{tid}을 찾을 수 없거나 이미 완료됨"

        # 할일 취소
        m = re.search(r'(?:할일|할 일|todo)\s*(?:#?\s*)?(\d+)\s*(?:번?\s*)?취소', low)
        if m:
            tid = int(m.group(1))
            if cancel_todo(tid):
                return f"🚫 할일 #{tid} 취소됨"
            return f"할일 #{tid}을 찾을 수 없음"

        # 할일 삭제
        m = re.search(r'(?:할일|할 일|todo)\s*(?:#?\s*)?(\d+)\s*(?:번?\s*)?삭제', low)
        if m:
            tid = int(m.group(1))
            if delete_todo(tid):
                return f"🗑 할일 #{tid} 삭제됨"
            return f"할일 #{tid}을 찾을 수 없음"

        # 할일 목록
        if any(kw in low for kw in ['할일 목록', '할 일 목록', '할일 보여', '할 일 보여',
                                      '할일 리스트', 'todo 목록', '할일 전체', '해야할 거']):
            show_all = '전체' in low or '모두' in low or '완료' in low
            todos = list_todos(status='all' if show_all else 'pending')
            if not todos:
                return "할일이 없습니다! 🎉"
            return self._format_list(todos, "전체" if show_all else "대기 중")

        # 할일 추가
        content = extract_content(text)
        if not content or len(content) < 2:
            # 목록 표시 (아무것도 지정하지 않은 경우)
            todos = list_todos(status='pending')
            if not todos:
                return "할일이 없습니다! 🎉\n할일 추가: \"할일 추가 세금 신고\""
            return self._format_list(todos, "대기 중")

        priority = detect_priority(text)
        due_date = parse_due_date(text)

        tid = add_todo(content, priority=priority, due_date=due_date)

        pri_emoji = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}[priority]
        due_str = f"\n기한: {due_date}" if due_date else ""
        return f"{pri_emoji} 할일 #{tid} 추가: {content}{due_str}"

    def handle_command(self, args: str, chat_id: str, context: dict) -> str:
        """슬래시 명령 /todo 처리."""
        if not args.strip():
            todos = list_todos(status='pending')
            if not todos:
                return "할일이 없습니다! 🎉"
            return self._format_list(todos, "대기 중")
        return self.handle(args, chat_id, context)

    def _format_list(self, todos: list[dict], title: str) -> str:
        lines = [f"✅ *할일 목록* — {title} ({len(todos)}건)", ""]
        for t in todos:
            pri = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(t['priority'], '⚪')
            status = {'pending': '⬜', 'done': '✅', 'cancelled': '🚫'}.get(t['status'], '?')
            content = t['content'][:60]
            due = f" 📅{t['due_date'][:10]}" if t.get('due_date') else ""
            lines.append(f"  {status} #{t['id']} {pri} {content}{due}")
        return '\n'.join(lines)

    def get_help(self) -> str:
        return """✅ *할일 에이전트*
/todo — 할일 목록
"할일 추가 세금 신고" — 추가
"긴급 할일 내일까지 보고서" — 우선순위+기한
"할일 2 완료" — 완료
"할일 3 삭제" — 삭제"""


todo_agent = TodoAgent()
register_agent(todo_agent)
