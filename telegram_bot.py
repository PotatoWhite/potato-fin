#!/usr/bin/env python3
"""
텔레그램 인터랙티브 봇 (Telegram Interactive Bot)

장기 실행 폴링 봇으로, 텔레그램에서 명령어를 받아 실시간 정보를 제공한다.

Commands:
    /thesis     — 현재 투자 테제 요약
    /price      — 전 종목 현재가 + 등락
    /price NVDA — 특정 종목 현재가 + 테제 판단
    /portfolio  — 포트폴리오 성과 요약
    /weekly     — 주간 예측 회고
    /validate   — 최신 보고서 검증 결과
    /help       — 명령어 목록

Usage:
    python3 telegram_bot.py              # 폴링 봇 시작
    python3 telegram_bot.py --once CMD   # 단일 명령 실행 후 종료
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
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


def send_message(text: str, chat_id: str = CHAT_ID):
    """텔레그램 메시지 전송 (4096자 제한 분할)."""
    MAX_LEN = 4000
    chunks = [text[i:i+MAX_LEN] for i in range(0, len(text), MAX_LEN)]
    for chunk in chunks:
        data = json.dumps({
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }).encode('utf-8')
        req = urllib.request.Request(
            f"{API}/sendMessage", data=data,
            headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            # Markdown 파싱 실패 시 plain text로 재시도
            data = json.dumps({
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }).encode('utf-8')
            req = urllib.request.Request(
                f"{API}/sendMessage", data=data,
                headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=10)
            except Exception:
                pass


def cmd_thesis() -> str:
    """투자 테제 요약."""
    sys.path.insert(0, str(STOCK_DIR))
    from update_thesis import format_thesis_summary
    return format_thesis_summary()


def cmd_price(ticker: str = '') -> str:
    """종목 현재가 조회."""
    import yfinance as yf
    sys.path.insert(0, str(STOCK_DIR))
    from update_thesis import load_thesis, ALL_TICKERS, TICKER_NAMES

    thesis = load_thesis()
    tickers_data = thesis.get('tickers', {})

    if ticker:
        # 특정 종목
        ticker = ticker.upper()
        # 단축명 매칭
        matches = [t for t in ALL_TICKERS if ticker in t or ticker in t.split('.')[0]]
        if not matches:
            return f"종목을 찾을 수 없습니다: {ticker}"

        target = matches[0]
        try:
            data = yf.download([target], period='2d', progress=False, group_by='ticker')
            # 단일 티커: MultiIndex 처리
            try:
                close = data[target]['Close'].dropna()
            except (KeyError, TypeError):
                close = data['Close'].dropna()
                if hasattr(close, 'columns'):
                    close = close[target].dropna()
            if len(close) >= 2:
                price = float(close.iloc[-1])
                prev = float(close.iloc[-2])
                change = price - prev
                change_pct = change / prev * 100
            elif len(close) == 1:
                price = float(close.iloc[-1])
                change = 0
                change_pct = 0
            else:
                return f"{target}: 가격 조회 실패"
        except Exception as e:
            return f"{target}: 가격 조회 실패 ({e})"

        sign = '+' if change >= 0 else ''
        name = TICKER_NAMES.get(target, target)

        lines = [f"*{name}* ({target})"]
        if '.KS' in target or '.KQ' in target:
            lines.append(f"현재가: ₩{price:,.0f} ({sign}{change:,.0f} / {sign}{change_pct:.1f}%)")
        elif '.T' in target:
            lines.append(f"현재가: ¥{price:,.0f} ({sign}{change:,.0f} / {sign}{change_pct:.1f}%)")
        elif '.DE' in target:
            lines.append(f"현재가: €{price:.2f} ({sign}{change:.2f} / {sign}{change_pct:.1f}%)")
        else:
            lines.append(f"현재가: ${price:.2f} ({sign}{change:.2f} / {sign}{change_pct:.1f}%)")

        # 테제 정보
        tdata = tickers_data.get(target, {})
        if tdata:
            j = {'buy': '매수', 'sell': '매도', 'hold': '보유', 'watch': '관망'}.get(
                tdata.get('judgment', ''), '?')
            d = {'bullish': '강세', 'bearish': '약세', 'neutral': '중립',
                 'mild_bullish': '약강세', 'mild_bearish': '약약세'}.get(
                tdata.get('direction', ''), '?')
            conv = tdata.get('conviction', 5)
            score = tdata.get('scores', {}).get('total', 0)
            pred = tdata.get('predictions', {}).get('5d', {}).get('price', '?')
            stop = tdata.get('stop_loss', '?')
            target_p = tdata.get('target', '?')

            lines.append(f"테제: {j} / {d} (확신 {conv}/10)")
            lines.append(f"점수: {score:+.1f}")
            lines.append(f"5일 예측: {pred}")
            lines.append(f"손절: {stop} | 목표: {target_p}")
            labels = tdata.get('special_labels', [])
            if labels:
                lines.append(f"경고: {', '.join(labels)}")

        return '\n'.join(lines)

    else:
        # 전 종목 간략 현재가
        try:
            data = yf.download(ALL_TICKERS, period='2d', progress=False, group_by='ticker')
        except Exception as e:
            return f"가격 조회 실패: {e}"

        lines = ["*전 종목 현재가*", ""]
        for t in ALL_TICKERS:
            try:
                if len(ALL_TICKERS) == 1:
                    col = data['Close'].dropna()
                else:
                    col = data[t]['Close'].dropna()
                if len(col) >= 2:
                    price = float(col.iloc[-1])
                    prev = float(col.iloc[-2])
                    pct = (price - prev) / prev * 100
                elif len(col) == 1:
                    price = float(col.iloc[-1])
                    pct = 0
                else:
                    continue
            except Exception:
                continue

            sign = '+' if pct >= 0 else ''
            name = TICKER_NAMES.get(t, t)[:6]

            if '.KS' in t or '.KQ' in t:
                p_str = f"₩{price:>8,.0f}"
            elif '.T' in t:
                p_str = f"¥{price:>6,.0f}"
            elif '.DE' in t:
                p_str = f"€{price:>7.2f}"
            else:
                p_str = f"${price:>7.2f}"

            lines.append(f"`{name:<6} {p_str} {sign}{pct:.1f}%`")

        return '\n'.join(lines)


def cmd_portfolio() -> str:
    """포트폴리오 성과 요약."""
    sys.path.insert(0, str(STOCK_DIR))
    from portfolio_tracker import format_summary
    return format_summary()


def cmd_weekly() -> str:
    """주간 예측 회고."""
    sys.path.insert(0, str(STOCK_DIR))
    from update_thesis import weekly_retrospective
    return weekly_retrospective()


def cmd_validate() -> str:
    """최신 보고서 검증."""
    sys.path.insert(0, str(STOCK_DIR))
    from validate_report import validate_report, format_result

    report_dir = STOCK_DIR / "보고서"
    reports = sorted(report_dir.glob("20*.md"))
    if not reports:
        return "보고서 없음"

    latest = reports[-1]
    result = validate_report(str(latest))
    return format_result(result)


def cmd_help() -> str:
    """명령어 목록."""
    return """📋 *명령어 목록*

/t — 투자 테제 요약
/p — 전 종목 현재가
/p NVDA — 종목 상세
/pf — 포트폴리오 성과
/w — 주간 예측 회고
/v — 보고서 검증
/h — 도움말

_긴 명령어도 가능: /thesis /price /portfolio /weekly /validate /help_"""


COMMANDS = {
    # 단축 명령어
    '/t': lambda args: cmd_thesis(),
    '/p': lambda args: cmd_price(args),
    '/pf': lambda args: cmd_portfolio(),
    '/w': lambda args: cmd_weekly(),
    '/v': lambda args: cmd_validate(),
    '/h': lambda args: cmd_help(),
    # 풀 명령어
    '/thesis': lambda args: cmd_thesis(),
    '/price': lambda args: cmd_price(args),
    '/portfolio': lambda args: cmd_portfolio(),
    '/weekly': lambda args: cmd_weekly(),
    '/validate': lambda args: cmd_validate(),
    '/help': lambda args: cmd_help(),
    '/start': lambda args: cmd_help(),
}


def handle_message(text: str, chat_id: str) -> str | None:
    """메시지 처리."""
    text = text.strip()
    if not text.startswith('/'):
        return None

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().split('@')[0]  # /price@botname → /price
    args = parts[1] if len(parts) > 1 else ''

    handler = COMMANDS.get(cmd)
    if handler:
        try:
            return handler(args)
        except Exception as e:
            return f"오류: {e}"
    return None


def poll_updates():
    """텔레그램 Long Polling으로 메시지 수신."""
    print(f"[BOT] 시작 — {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    offset = 0

    while True:
        try:
            url = f"{API}/getUpdates?offset={offset}&timeout=30"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read().decode('utf-8'))

            if not data.get('ok'):
                time.sleep(5)
                continue

            for update in data.get('result', []):
                offset = update['update_id'] + 1
                msg = update.get('message', {})
                text = msg.get('text', '')
                chat_id = str(msg.get('chat', {}).get('id', ''))

                if not text or chat_id != CHAT_ID:
                    continue

                print(f"[BOT] {chat_id}: {text}")
                response = handle_message(text, chat_id)
                if response:
                    send_message(response, chat_id)

        except KeyboardInterrupt:
            print("\n[BOT] 종료")
            break
        except Exception as e:
            print(f"[BOT] 오류: {e}")
            time.sleep(5)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='텔레그램 인터랙티브 봇')
    parser.add_argument('--once', type=str, help='단일 명령 실행 (예: /thesis)')
    args = parser.parse_args()

    if not BOT_TOKEN or not CHAT_ID:
        print("[ERROR] TELEGRAM_BOT_TOKEN/CHAT_ID가 .env에 설정되지 않았습니다",
              file=sys.stderr)
        sys.exit(1)

    if args.once:
        response = handle_message(args.once, CHAT_ID)
        if response:
            print(response)
            send_message(response)
        else:
            print(f"알 수 없는 명령: {args.once}")
    else:
        poll_updates()


if __name__ == '__main__':
    main()
