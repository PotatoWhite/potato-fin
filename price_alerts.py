#!/usr/bin/env python3
"""가격 알림 모니터링

현재 개장 중인 시장의 종목을 조회하여:
- 손절선 도달
- 목표가 도달
- 일중 급등락 (swing_pct 이상)
발생 시 macOS 알림을 보낸다.
"""

import json
import logging
import os
import subprocess
from datetime import datetime

import yfinance as yf

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "alert_config.json")
STATE_FILE = os.path.join(BASE_DIR, ".alert_state.json")
LOG_DIR = os.path.expanduser("~/logs/stock-monitor")

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "alerts.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        # 일일 리셋: 날짜가 다르면 초기화
        if state.get("date") != datetime.now().strftime("%Y-%m-%d"):
            return {"date": datetime.now().strftime("%Y-%m-%d"), "sent": {}}
        return state
    return {"date": datetime.now().strftime("%Y-%m-%d"), "sent": {}}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def is_market_open(market_config, now=None):
    """현재 시간(KST)이 시장 개장 시간인지 확인"""
    if now is None:
        now = datetime.now()
    current_minutes = now.hour * 60 + now.minute
    open_minutes = market_config["open_hour_kst"] * 60 + market_config["open_minute"]
    close_minutes = market_config["close_hour_kst"] * 60 + market_config["close_minute"]

    if open_minutes < close_minutes:
        # 같은 날 (예: KR 09:00~15:30)
        return open_minutes <= current_minutes <= close_minutes
    else:
        # 자정 넘김 (예: US 23:30~06:00)
        return current_minutes >= open_minutes or current_minutes <= close_minutes


def send_notification(title, message, sound="Glass"):
    """알림 전송 (Linux: notify-send, macOS: osascript)"""
    import platform
    logging.info(f"[ALERT] {title}: {message}")
    try:
        if platform.system() == "Darwin":
            script = f'''display notification "{message}" with title "{title}" sound name "{sound}"'''
            subprocess.run(["osascript", "-e", script], check=True, timeout=10)
        else:
            subprocess.run(["notify-send", title, message], check=True, timeout=10)
    except Exception as e:
        logging.warning(f"알림 전송 실패 (로그에 기록됨): {e}")


def check_alerts():
    config = load_config()
    state = load_state()
    markets = config["markets"]
    alerts = config["alerts"]
    now = datetime.now()

    # 현재 개장 중인 시장의 종목만 필터
    active_tickers = {}
    for ticker, alert_cfg in alerts.items():
        market_key = alert_cfg["market"]
        if market_key in markets and is_market_open(markets[market_key], now):
            active_tickers[ticker] = alert_cfg

    if not active_tickers:
        logging.info("현재 개장 중인 시장 없음")
        return

    logging.info(f"조회 대상: {list(active_tickers.keys())}")

    # 일괄 조회
    ticker_list = list(active_tickers.keys())
    try:
        data = yf.download(ticker_list, period="1d", progress=False)
    except Exception as e:
        logging.error(f"데이터 조회 실패: {e}")
        return

    for ticker, alert_cfg in active_tickers.items():
        name = alert_cfg["name"]
        try:
            if len(ticker_list) == 1:
                close = float(data["Close"].iloc[-1])
                open_price = float(data["Open"].iloc[-1])
            else:
                close = float(data["Close"][ticker].iloc[-1])
                open_price = float(data["Open"][ticker].iloc[-1])
        except Exception:
            logging.warning(f"{ticker} 가격 조회 실패")
            continue

        sent_key = f"{ticker}_{now.strftime('%Y%m%d')}"
        sent = state["sent"].get(sent_key, [])

        # 손절선 체크
        stop_loss = alert_cfg.get("stop_loss")
        if stop_loss and close <= stop_loss and "stop_loss" not in sent:
            msg = f"{name} ₩{close:,.0f} ≤ 손절선 ₩{stop_loss:,.0f}"
            send_notification("🔴 손절선 도달", msg, "Sosumi")
            logging.warning(msg)
            sent.append("stop_loss")

        # 목표가 체크
        target = alert_cfg.get("target")
        if target and close >= target and "target" not in sent:
            msg = f"{name} ₩{close:,.0f} ≥ 목표가 ₩{target:,.0f}"
            send_notification("🟢 목표가 도달", msg)
            logging.info(msg)
            sent.append("target")

        # 급등락 체크
        swing_pct = alert_cfg.get("swing_pct", 3.0)
        if open_price > 0:
            change_pct = (close - open_price) / open_price * 100
            if abs(change_pct) >= swing_pct and "swing" not in sent:
                direction = "급등" if change_pct > 0 else "급락"
                emoji = "📈" if change_pct > 0 else "📉"
                msg = f"{name} {change_pct:+.1f}% ({close:,.2f})"
                send_notification(f"{emoji} {direction} 알림", msg)
                logging.info(msg)
                sent.append("swing")

        state["sent"][sent_key] = sent

    save_state(state)
    logging.info("알림 체크 완료")


if __name__ == "__main__":
    check_alerts()
