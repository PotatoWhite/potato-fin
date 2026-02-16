#!/usr/bin/env python3
"""
개인비서 에이전트 봇 (Multi-Agent Personal Assistant)

텔레그램을 창구로, 8개 전문 에이전트가 각 도메인을 처리한다.
기존 금융 시스템(telegram_bot.py) 100% 보존.

에이전트:
    💰 finance   — 주식/포트폴리오/투자
    📝 memo      — 메모/노트 저장·검색·삭제
    ✅ todo      — 할일/작업 관리
    ⏰ calendar  — 리마인더/일정 알림
    🔍 search    — 웹 검색/리서치
    ✈️ travel    — 여행 계획/정보
    💬 general   — 일반 대화/Q&A
    🔧 develop   — 코드 개선

Usage:
    python3 assistant_bot.py              # 폴링 봇 시작
    python3 assistant_bot.py --once CMD   # 단일 명령 실행 후 종료
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

STOCK_DIR = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))

# .env 로드
_env_file = STOCK_DIR / ".env"
if _env_file.exists():
    for line in _env_file.read_text().strip().split('\n'):
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip()

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# sys.path 설정
if str(STOCK_DIR) not in sys.path:
    sys.path.insert(0, str(STOCK_DIR))

# DB 초기화
from assistant_db import init_db, save_conversation, get_recent_conversations, cleanup_old_conversations
init_db()
cleanup_old_conversations(90)  # 90일 이상 대화 로그 정리

# 에이전트 임포트 (레지스트리에 자동 등록)
from agents import AGENTS
from agents.finance import finance_agent
from agents.memo import memo_agent
from agents.todo import todo_agent
from agents.calendar import calendar_agent
from agents.search import search_agent
from agents.travel import travel_agent
from agents.general import general_agent
from agents.develop import develop_agent
from agents.router import route


# ── 메시지 전송 ────────────────────────────────────────

def send_message(text: str, chat_id: str = None):
    """텔레그램 메시지 전송 (4096자 제한 분할, 네트워크 재시도)."""
    if not text or not text.strip():
        return
    chat_id = chat_id or CHAT_ID
    MAX_LEN = 4000
    chunks = [text[i:i+MAX_LEN] for i in range(0, len(text), MAX_LEN)]

    def _send_with_retry(data: bytes, max_retries: int = 3) -> bool:
        """네트워크 일시 장애 대응 재시도."""
        import socket
        for attempt in range(max_retries):
            req = urllib.request.Request(
                f"{API}/sendMessage", data=data,
                headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=10)
                return True
            except (socket.error, OSError) as e:
                # Network unreachable, connection refused 등
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # 1초, 2초, 4초 지수 백오프
                    continue
                return False
            except Exception:
                return False
        return False

    for chunk in chunks:
        # Markdown 시도
        data = json.dumps({
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }).encode('utf-8')
        if _send_with_retry(data):
            continue

        # Markdown 실패 시 plain text 재시도
        data = json.dumps({
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }).encode('utf-8')
        _send_with_retry(data)


# ── 컨텍스트 빌드 ──────────────────────────────────────

def build_context(chat_id: str) -> dict:
    """에이전트에 전달할 컨텍스트 구성."""
    conversations = get_recent_conversations(chat_id, limit=6)
    # 직전 응답 추출
    last_response = ''
    last_agent = ''
    for c in reversed(conversations):
        if c.get('role') == 'assistant':
            last_response = c.get('content', '')
            last_agent = c.get('agent', '')
            break

    return {
        'chat_id': chat_id,
        'last_response': last_response,
        'last_agent': last_agent,
        'conversation': conversations,
        'send_fn': send_message,
    }


# ── 도움말 ─────────────────────────────────────────────

def show_help() -> str:
    return """*개인비서 봇* 🤖

*금융 (💰):*
/p — 전 종목 현재가
/p NVDA — 종목 상세
/pf — 포트폴리오 추이
/s — 실시간 스냅샷
/t — 투자 테제
/r — 최신 보고서
/a — 알림 설정
/m — 감시병 현황
/ac — 예측 정확도
/w — 주간 회고
/v — 보고서 검증

*비서 (📝✅⏰):*
/memo — 메모 목록/저장
/todo — 할일 목록/추가
/remind — 리마인더 목록/설정

*기타 (🔍✈️💬🔧):*
/search — 웹 검색
/travel — 여행 도우미

*자유 텍스트도 OK:*
"삼성전자 어때" → 💰 종목 분석
"메모해 내일 회의" → 📝 메모 저장
"할일 추가 세금 신고" → ✅ 할일 추가
"30분 후 알려줘" → ⏰ 리마인더
"트럼프 관세 검색" → 🔍 웹 검색
"도쿄 여행 계획" → ✈️ 여행 도우미
"안녕" → 💬 일반 대화

*실행 명령:*
"보고서 만들어" → US 보고서 ($10-15)
"한국 보고서" → 한국 보고서 ($8-10)
"개선해 XX" → 🔧 코드 수정 ($5 이내)"""


# ── 슬래시 명령어 매핑 ─────────────────────────────────

SLASH_COMMANDS = {
    # 금융 (기존 그대로)
    '/t': 'finance', '/thesis': 'finance',
    '/p': 'finance', '/price': 'finance',
    '/pf': 'finance', '/portfolio': 'finance',
    '/s': 'finance', '/snapshot': 'finance',
    '/r': 'finance', '/report': 'finance',
    '/a': 'finance', '/alert': 'finance',
    '/m': 'finance', '/monitor': 'finance',
    '/ac': 'finance', '/accuracy': 'finance',
    '/w': 'finance', '/weekly': 'finance',
    '/v': 'finance', '/validate': 'finance',
    # 비서
    '/memo': 'memo',
    '/todo': 'todo',
    '/remind': 'calendar', '/reminder': 'calendar',
    # 기타
    '/search': 'search',
    '/travel': 'travel',
}


# ── 메시지 핸들러 ──────────────────────────────────────

def handle_message(text: str, chat_id: str) -> tuple[str | None, str]:
    """메시지 처리 → (응답, 에이전트명) 튜플 반환."""
    text = text.strip()
    if not text:
        return None, ''

    context = build_context(chat_id)

    # 1) 슬래시 명령어
    if text.startswith('/'):
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().split('@')[0]
        args = parts[1] if len(parts) > 1 else ''

        # help
        if cmd in ('/h', '/help', '/start'):
            return show_help(), 'help'

        # 금융 슬래시 → finance 에이전트의 전용 핸들러
        agent_name = SLASH_COMMANDS.get(cmd)
        if agent_name == 'finance':
            result = finance_agent.handle_slash(cmd, args)
            if result is not None:
                return result, 'finance'

        # 비서/기타 슬래시
        if agent_name and agent_name in AGENTS:
            agent = AGENTS[agent_name]
            try:
                return agent.handle_command(args, chat_id, context), agent_name
            except Exception as e:
                return f"오류: {e}", agent_name

        return f"알 수 없는 명령: {cmd}\n/h 로 명령어 목록 확인", ''

    # 2) 도움말 자유 텍스트
    low = text.lower().strip()
    if any(kw in low for kw in ['도움', '도움말', '명령어', '뭐할수', '뭐 할 수']):
        return show_help(), 'help'

    # 3) 자유 텍스트 → 라우터 (1회만 호출)
    try:
        agent_name = route(text, context)
        agent = AGENTS.get(agent_name)
        if not agent:
            agent = AGENTS.get('general', general_agent)
            agent_name = 'general'

        response = agent.handle(text, chat_id, context)
        return (response if response else None), agent_name
    except Exception as e:
        return f"처리 오류: {e}", ''


# ── 폴링 루프 ─────────────────────────────────────────

def poll_updates():
    """텔레그램 Long Polling으로 메시지 수신."""
    print(f"[BOT] 개인비서 봇 시작 — {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    print(f"[BOT] 등록된 에이전트: {', '.join(AGENTS.keys())}")

    # 리마인더 체커 시작
    calendar_agent.start_checker(send_message, CHAT_ID)
    print("[BOT] 리마인더 체커 시작됨 (30초 간격)")

    offset = 0
    fail_count = 0

    while True:
        try:
            url = f"{API}/getUpdates?offset={offset}&timeout=30"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read().decode('utf-8'))

            if not data.get('ok'):
                fail_count += 1
                time.sleep(5)
                continue

            fail_count = 0  # 성공 시 백오프 리셋

            for update in data.get('result', []):
                offset = update['update_id'] + 1
                msg = update.get('message', {})
                text = msg.get('text', '')
                chat_id = str(msg.get('chat', {}).get('id', ''))

                if not text or chat_id != CHAT_ID:
                    continue

                print(f"[BOT] {chat_id}: {text}")

                # 대화 로그 저장
                save_conversation(chat_id, 'user', text)

                # 처리
                response, agent_name = handle_message(text, chat_id)
                if response:
                    send_message(response, chat_id)
                    save_conversation(chat_id, 'assistant', response[:1000], agent=agent_name)

        except KeyboardInterrupt:
            print("\n[BOT] 종료")
            break
        except Exception as e:
            fail_count += 1
            backoff = min(5 * (2 ** min(fail_count - 1, 5)), 300)  # 5→10→20→40→80→160→300
            print(f"[BOT] 오류 (#{fail_count}, {backoff}초 대기): {e}")
            time.sleep(backoff)


# ── CLI ────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description='개인비서 에이전트 봇')
    parser.add_argument('--once', type=str, help='단일 명령 실행 (예: /thesis)')
    args = parser.parse_args()

    if not BOT_TOKEN or not CHAT_ID:
        print("[ERROR] TELEGRAM_BOT_TOKEN/CHAT_ID가 .env에 설정되지 않았습니다",
              file=sys.stderr)
        sys.exit(1)

    if args.once:
        response, _ = handle_message(args.once, CHAT_ID)
        if response:
            print(response)
            send_message(response)
        else:
            print(f"알 수 없는 명령: {args.once}")
    else:
        poll_updates()


if __name__ == '__main__':
    main()
