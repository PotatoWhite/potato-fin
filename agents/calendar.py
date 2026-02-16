"""
리마인더/일정 에이전트 — 자연어 날짜 파싱 + 알림

백그라운드 스레드로 30초마다 체크, due 시각에 텔레그램 알림.
"""

import re
import threading
import time
from datetime import datetime, timedelta

from agents import BaseAgent, register_agent
from assistant_db import (
    add_reminder, list_reminders, cancel_reminder,
    get_due_reminders, mark_fired, reschedule_reminder
)

WEEKDAY_MAP = {
    '월': 0, '화': 1, '수': 2, '목': 3, '금': 4, '토': 5, '일': 6,
    '월요일': 0, '화요일': 1, '수요일': 2, '목요일': 3, '금요일': 4, '토요일': 5, '일요일': 6,
}


def parse_datetime(text: str) -> tuple[str | None, str | None]:
    """자연어 → (remind_at YYYY-MM-DD HH:MM, recurring)."""
    now = datetime.now()
    low = text.lower().strip()

    # "N분 후"
    m = re.search(r'(\d+)\s*분\s*(?:후|뒤|있다가)', low)
    if m:
        dt = now + timedelta(minutes=int(m.group(1)))
        return dt.strftime('%Y-%m-%d %H:%M'), None

    # "N시간 후"
    m = re.search(r'(\d+)\s*시간\s*(?:후|뒤)', low)
    if m:
        dt = now + timedelta(hours=int(m.group(1)))
        return dt.strftime('%Y-%m-%d %H:%M'), None

    # "매일 N시" (recurring)
    m = re.search(r'매일\s*(\d{1,2})\s*시\s*(\d{1,2})?분?', low)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        dt = now.replace(hour=hour, minute=minute, second=0)
        if dt <= now:
            dt += timedelta(days=1)
        return dt.strftime('%Y-%m-%d %H:%M'), 'daily'

    # "매주 X요일 N시" (recurring)
    m = re.search(r'매주\s*(월|화|수|목|금|토|일)(?:요일)?\s*(\d{1,2})\s*시\s*(\d{1,2})?분?', low)
    if m:
        target_day = WEEKDAY_MAP[m.group(1)]
        hour = int(m.group(2))
        minute = int(m.group(3)) if m.group(3) else 0
        days_ahead = (target_day - now.weekday()) % 7
        if days_ahead == 0 and now.hour * 60 + now.minute >= hour * 60 + minute:
            days_ahead = 7
        dt = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0)
        return dt.strftime('%Y-%m-%d %H:%M'), 'weekly'

    # "내일 N시" (오후 감지 포함)
    m = re.search(r'내일\s*(?:오후\s*)?(\d{1,2})\s*시\s*(\d{1,2})?분?', low)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        if '오후' in low and hour < 12:
            hour += 12
        dt = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0)
        return dt.strftime('%Y-%m-%d %H:%M'), None

    # "모레 N시" (오후 감지 포함)
    m = re.search(r'(?:모레|모래)\s*(?:오후\s*)?(\d{1,2})\s*시\s*(\d{1,2})?분?', low)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        if '오후' in low and hour < 12:
            hour += 12
        dt = (now + timedelta(days=2)).replace(hour=hour, minute=minute, second=0)
        return dt.strftime('%Y-%m-%d %H:%M'), None

    # "N시에" 또는 "N시 M분에" (오후 감지 포함, 오늘, 지났으면 내일)
    m = re.search(r'(?:오후\s*)?(\d{1,2})\s*시\s*(\d{1,2})?분?\s*(?:에|까지)?', low)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        if '오후' in low and hour < 12:
            hour += 12
        dt = now.replace(hour=hour, minute=minute, second=0)
        if dt <= now:
            dt += timedelta(days=1)
        return dt.strftime('%Y-%m-%d %H:%M'), None

    # "다음주 X요일"
    m = re.search(r'다음\s*주?\s*(월|화|수|목|금|토|일)(?:요일)?\s*(\d{1,2})?\s*시?\s*(\d{1,2})?분?', low)
    if m:
        target_day = WEEKDAY_MAP[m.group(1)]
        hour = int(m.group(2)) if m.group(2) else 9
        minute = int(m.group(3)) if m.group(3) else 0
        days_ahead = (target_day - now.weekday()) % 7 + 7
        dt = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0)
        return dt.strftime('%Y-%m-%d %H:%M'), None

    # "M/D N시" 또는 "M월 D일 N시"
    m = re.search(r'(\d{1,2})[/월]\s*(\d{1,2})[일]?\s*(\d{1,2})?\s*시?\s*(\d{1,2})?분?', low)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        hour = int(m.group(3)) if m.group(3) else 9
        minute = int(m.group(4)) if m.group(4) else 0
        try:
            dt = now.replace(month=month, day=day, hour=hour, minute=minute, second=0)
            if dt < now:
                dt = dt.replace(year=dt.year + 1)
            return dt.strftime('%Y-%m-%d %H:%M'), None
        except ValueError:
            pass

    return None, None


def extract_content(text: str) -> str:
    """리마인더 내용 추출 (시간 표현 제거)."""
    content = text
    # 접두어 제거
    for prefix in ['리마인더', '알려줘', '알람', '알려줘:', '리마인더:', '알림 설정']:
        if content.lower().startswith(prefix):
            content = content[len(prefix):].strip()
            break

    content = content.lstrip('-:').strip()

    # 시간 표현 제거
    patterns = [
        r'\d+\s*분\s*(?:후|뒤|있다가)', r'\d+\s*시간\s*(?:후|뒤)',
        r'매일\s*\d{1,2}\s*시\s*\d{0,2}분?',
        r'매주\s*(?:월|화|수|목|금|토|일)(?:요일)?\s*\d{0,2}\s*시?\s*\d{0,2}분?',
        r'내일\s*\d{1,2}\s*시\s*\d{0,2}분?', r'모[레래]\s*\d{1,2}\s*시\s*\d{0,2}분?',
        r'다음\s*주?\s*(?:월|화|수|목|금|토|일)(?:요일)?\s*\d{0,2}\s*시?\s*\d{0,2}분?',
        r'\d{1,2}[/월]\s*\d{1,2}[일]?\s*\d{0,2}\s*시?\s*\d{0,2}분?',
        r'\d{1,2}\s*시\s*\d{0,2}분?\s*(?:에|까지)?',
        r'에\s*알려줘', r'알려줘',
    ]
    for p in patterns:
        content = re.sub(p, '', content).strip()

    content = content.strip(' -:')
    return content


def calc_next_recurring(remind_at: str, recurring: str) -> str:
    """다음 반복 시각 계산."""
    dt = datetime.strptime(remind_at, '%Y-%m-%d %H:%M')
    if recurring == 'daily':
        dt += timedelta(days=1)
    elif recurring == 'weekly':
        dt += timedelta(weeks=1)
    elif recurring == 'monthly':
        month = dt.month + 1
        year = dt.year
        if month > 12:
            month = 1
            year += 1
        try:
            dt = dt.replace(year=year, month=month)
        except ValueError:
            dt = dt.replace(year=year, month=month, day=28)
    return dt.strftime('%Y-%m-%d %H:%M')


class CalendarAgent(BaseAgent):
    name = 'calendar'
    description = '리마인더/일정 알림'
    emoji = '⏰'

    _checker_started = False
    _send_fn = None
    _chat_id = None

    def start_checker(self, send_fn, chat_id: str = None):
        """리마인더 체커 백그라운드 스레드 시작."""
        if CalendarAgent._checker_started:
            return
        CalendarAgent._checker_started = True
        CalendarAgent._send_fn = send_fn
        CalendarAgent._chat_id = chat_id

        def _check_loop():
            while True:
                try:
                    due = get_due_reminders()
                    for r in due:
                        # 먼저 상태 변경 (중복 발동 방지)
                        if r.get('recurring'):
                            next_at = calc_next_recurring(r['remind_at'], r['recurring'])
                            reschedule_reminder(r['id'], next_at)
                        else:
                            mark_fired(r['id'])
                        # 그 후 알림 전송
                        if CalendarAgent._send_fn:
                            recurring_str = f" (🔄 {r['recurring']})" if r.get('recurring') else ""
                            CalendarAgent._send_fn(
                                f"⏰ *리마인더*\n{r['content']}{recurring_str}",
                                CalendarAgent._chat_id
                            )
                except Exception as e:
                    print(f"[REMINDER] 체커 오류: {e}")
                time.sleep(30)

        t = threading.Thread(target=_check_loop, daemon=True)
        t.start()

    def handle(self, text: str, chat_id: str, context: dict) -> str:
        low = text.lower().strip()

        # 리마인더 취소
        m = re.search(r'(?:리마인더|알람|알림)\s*(?:#?\s*)?(\d+)\s*(?:번?\s*)?(?:취소|삭제)', low)
        if m:
            rid = int(m.group(1))
            if cancel_reminder(rid):
                return f"🚫 리마인더 #{rid} 취소됨"
            return f"리마인더 #{rid}을 찾을 수 없음"

        # 리마인더 목록
        if any(kw in low for kw in ['리마인더 목록', '리마인더 보여', '알람 목록',
                                      '일정 목록', '알림 목록', '리마인더 리스트']):
            reminders = list_reminders(status='active')
            if not reminders:
                return "활성 리마인더가 없습니다."
            return self._format_list(reminders)

        # 리마인더 설정
        remind_at, recurring = parse_datetime(text)
        if not remind_at:
            return "시간을 인식하지 못했습니다.\n예: \"30분 후 알려줘 약 먹기\"\n예: \"내일 3시에 회의 알려줘\"\n예: \"매일 8시 운동 알려줘\""

        content = extract_content(text)
        if not content or len(content) < 2:
            content = "알림"

        rid = add_reminder(content, remind_at, recurring)
        recurring_str = f" (🔄 {recurring})" if recurring else ""
        return f"⏰ 리마인더 #{rid} 설정\n📅 {remind_at}{recurring_str}\n📝 {content}"

    def handle_command(self, args: str, chat_id: str, context: dict) -> str:
        """슬래시 명령 /remind 처리."""
        if not args.strip():
            reminders = list_reminders(status='active')
            if not reminders:
                return "활성 리마인더가 없습니다."
            return self._format_list(reminders)
        return self.handle(args, chat_id, context)

    def _format_list(self, reminders: list[dict]) -> str:
        lines = [f"⏰ *리마인더 목록* ({len(reminders)}건)", ""]
        for r in reminders:
            recurring = f" 🔄{r['recurring']}" if r.get('recurring') else ""
            lines.append(f"  #{r['id']} 📅 {r['remind_at']}{recurring}")
            lines.append(f"    {r['content']}")
        return '\n'.join(lines)

    def get_help(self) -> str:
        return """⏰ *리마인더 에이전트*
/remind — 리마인더 목록
"30분 후 알려줘 약 먹기" — 타이머
"내일 3시에 회의" — 일정
"매일 8시 운동 알려줘" — 반복
"매주 월요일 9시 회의" — 주간 반복
"리마인더 3 취소" — 취소"""


calendar_agent = CalendarAgent()
register_agent(calendar_agent)
