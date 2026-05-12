#!/usr/bin/env python3
"""
실시간 가격 추적기 — 장중 1분마다 cron으로 실행

DB 테이블: realtime_prices
  - KR 종목: 09:00~15:30 KST
  - US 종목: 23:30~06:00 KST (익일)

Usage:
    .venv/bin/python3 realtime_price_tracker.py
    .venv/bin/python3 realtime_price_tracker.py --init   # 테이블만 생성
    .venv/bin/python3 realtime_price_tracker.py --query TICKER [--limit N]  # 조회
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yfinance as yf

STOCK_DIR = Path(__file__).resolve().parent
DB_PATH = STOCK_DIR / "portfolio.db"

KST = timezone(timedelta(hours=9))

# 시장별 종목 (4/28 리셋 후 21종목)
KR_TICKERS = ['005930.KS', '000660.KS', '005380.KS',
              '035420.KS', '195940.KQ', '429760.KS']
US_TICKERS = ['NVDA', 'MSFT', 'GOOGL', 'TSLA', 'XOM', 'WRB', 'BOTZ', 'SLV',
              'GLD', 'IWM', 'LMT', 'WMB', 'XLE']
JP_TICKERS = ['1377.T']
DE_TICKERS = ['BAYN.DE']

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS realtime_prices (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ticker    TEXT NOT NULL,
    price     REAL,
    volume    INTEGER,
    UNIQUE(timestamp, ticker)
);
CREATE INDEX IF NOT EXISTS idx_rt_ticker_ts ON realtime_prices(ticker, timestamp);
"""

def init_table():
    with sqlite3.connect(DB_PATH) as conn:
        for stmt in CREATE_TABLE_SQL.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(s)
        conn.commit()
    print("realtime_prices 테이블 준비 완료")

def is_kr_open(now_kst: datetime) -> bool:
    """KR 장중 여부: 평일 09:00~15:30"""
    if now_kst.weekday() >= 5:
        return False
    t = now_kst.time()
    return t >= __import__('datetime').time(9, 0) and t <= __import__('datetime').time(15, 30)

def is_us_open(now_kst: datetime) -> bool:
    """US 장중 여부 (KST 기준): 평일 23:30(전일)~06:00"""
    # 월요일 KST 00:00 ~ 06:00 → 월 장중 (전주 금요일 US 세션 끝)
    # 실용적으로: 00:00~06:00 또는 23:30~23:59
    wd = now_kst.weekday()  # 0=월 ... 6=일
    t = now_kst.time()
    import datetime as dt
    early = t >= dt.time(0, 0) and t <= dt.time(6, 0)
    late  = t >= dt.time(23, 30)
    # 토요일 00~06 = 금요일 US 세션
    # 일요일 23:30 = 월요일 US 프리마켓 (포함)
    if early and wd in (1, 2, 3, 4, 5):   # 화~토 새벽 (월~금 US 세션)
        return True
    if late and wd in (0, 1, 2, 3, 6):    # 월~목, 일 밤 (US 세션 시작)
        return True
    return False

def is_jp_open(now_kst: datetime) -> bool:
    """JP 장중: 평일 09:00~15:30 JST (≈ KST 동일)"""
    return is_kr_open(now_kst)

def is_de_open(now_kst: datetime) -> bool:
    """DE 장중: 평일 09:00~17:30 CET = KST 17:00~01:30 (여름: 16:00~00:30)"""
    if now_kst.weekday() >= 5:
        return False
    t = now_kst.time()
    import datetime as dt
    return t >= dt.time(17, 0) or t <= dt.time(1, 30)

def fetch_prices(tickers: list[str]) -> dict:
    """yfinance로 현재가 일괄 조회"""
    if not tickers:
        return {}
    result = {}
    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).fast_info
            price = getattr(info, 'last_price', None)
            volume = getattr(info, 'last_volume', None)
            result[ticker] = {'price': price, 'volume': volume}
        except Exception as e:
            print(f"  {ticker} 조회 실패: {e}", file=sys.stderr)
    return result

def save_to_db(timestamp_str: str, prices: dict):
    """DB에 저장 (중복 무시)"""
    if not prices:
        return 0
    rows = [
        (timestamp_str, ticker, v['price'], v.get('volume'))
        for ticker, v in prices.items()
        if v.get('price') is not None
    ]
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO realtime_prices(timestamp, ticker, price, volume) VALUES (?,?,?,?)",
            rows
        )
        conn.commit()
    return len(rows)

def query(ticker: str, limit: int = 30):
    """최근 N건 조회"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT timestamp, price FROM realtime_prices WHERE ticker=? ORDER BY timestamp DESC LIMIT ?",
            (ticker, limit)
        ).fetchall()
    if not rows:
        print(f"{ticker}: 데이터 없음")
        return
    print(f"{'시각':25s} {'가격':>15s}")
    print("-" * 42)
    for ts, price in rows:
        print(f"{ts:25s} {price:>15,.2f}")

def main():
    init_table()
    now = datetime.now(KST)
    ts = now.strftime('%Y-%m-%d %H:%M')

    targets = []
    if is_kr_open(now):
        targets += KR_TICKERS
    if is_us_open(now):
        targets += US_TICKERS
    if is_jp_open(now):
        targets += JP_TICKERS
    if is_de_open(now):
        targets += DE_TICKERS

    # 중복 제거
    targets = list(dict.fromkeys(targets))

    if not targets:
        print(f"[{ts}] 개장 시장 없음 — 종료")
        return

    print(f"[{ts}] {len(targets)}종목 조회: {targets}")
    prices = fetch_prices(targets)
    saved = save_to_db(ts, prices)
    print(f"[{ts}] DB 저장 {saved}건")

    for ticker, v in prices.items():
        p = v.get('price')
        if p:
            print(f"  {ticker:15s}: {p:,.2f}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--init',  action='store_true', help='테이블만 생성')
    parser.add_argument('--query', metavar='TICKER',   help='최근 가격 조회')
    parser.add_argument('--limit', type=int, default=30)
    args = parser.parse_args()

    if args.init:
        init_table()
    elif args.query:
        init_table()
        query(args.query, args.limit)
    else:
        main()
