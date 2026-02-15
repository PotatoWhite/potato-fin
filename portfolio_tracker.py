#!/usr/bin/env python3
"""
포트폴리오 성과 추적 (Portfolio Performance Tracker)

일별 총 평가액/손익/수익률을 기록하고 추이를 제공한다.

Usage:
    python3 portfolio_tracker.py --snapshot     # 오늘 스냅샷 저장
    python3 portfolio_tracker.py --summary      # 성과 요약 출력 (보고서용)
    python3 portfolio_tracker.py --history N    # 최근 N일 히스토리
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

STOCK_DIR = Path(__file__).resolve().parent
HISTORY_FILE = STOCK_DIR / "data" / "portfolio_history.json"
KST = timezone(timedelta(hours=9))

FX_PAIRS = ['USDKRW=X', 'JPYKRW=X', 'EURKRW=X']

from portfolio_db import load_portfolio


def fetch_prices(portfolio: list[dict]) -> tuple[dict, dict]:
    """yfinance로 현재가 + 환율 조회."""
    tickers = [h['ticker'] for h in portfolio]
    data = yf.download(tickers + FX_PAIRS, period='5d', progress=False)

    prices = {}
    for h in portfolio:
        t = h['ticker']
        try:
            col = data['Close'][t].dropna()
            if not col.empty:
                prices[t] = round(float(col.iloc[-1]), 2)
        except Exception:
            pass

    fx = {'KRW': 1.0}
    for pair, key in [('USDKRW=X', 'USD'), ('JPYKRW=X', 'JPY'), ('EURKRW=X', 'EUR')]:
        try:
            col = data['Close'][pair].dropna()
            fx[key] = round(float(col.iloc[-1]), 2) if not col.empty else None
        except Exception:
            fx[key] = None

    return prices, fx


def take_snapshot() -> dict:
    """현재 포트폴리오 스냅샷 생성 & 저장."""
    portfolio = load_portfolio()
    prices, fx = fetch_prices(portfolio)

    total_krw = 0
    total_cost_krw = 0
    ticker_data = {}

    for h in portfolio:
        t = h['ticker']
        price = prices.get(t)
        if price is None:
            continue

        valuation = price * h['qty']
        rate = fx.get(h['currency'], 1.0) or 1.0
        val_krw = round(valuation * rate)
        cost_krw = round(h['cost'] * rate)
        pnl_krw = val_krw - cost_krw
        pnl_pct = round(pnl_krw / cost_krw * 100, 2) if cost_krw else 0

        total_krw += val_krw
        total_cost_krw += cost_krw

        ticker_data[t] = {
            'price': price,
            'qty': h['qty'],
            'val_krw': val_krw,
            'cost_krw': cost_krw,
            'pnl_krw': pnl_krw,
            'pnl_pct': pnl_pct,
        }

    total_pnl = total_krw - total_cost_krw
    total_pnl_pct = round(total_pnl / total_cost_krw * 100, 2) if total_cost_krw else 0

    snapshot = {
        'date': datetime.now(KST).strftime('%Y-%m-%d'),
        'time': datetime.now(KST).strftime('%H:%M'),
        'total_krw': total_krw,
        'total_cost_krw': total_cost_krw,
        'total_pnl_krw': total_pnl,
        'total_pnl_pct': total_pnl_pct,
        'fx': fx,
        'tickers': ticker_data,
    }

    # 저장
    history = load_history()
    # 같은 날 기존 항목 대체
    history = [s for s in history if s.get('date') != snapshot['date']]
    history.append(snapshot)
    # 최근 90일만 유지
    history = history[-90:]
    save_history(history)

    return snapshot


def load_history() -> list[dict]:
    """히스토리 파일 로드."""
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return []


def save_history(history: list[dict]):
    """히스토리 파일 저장."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )


def format_summary() -> str:
    """보고서용 성과 요약 출력.

    Output:
        [포트폴리오 성과]
        총 평가: ₩XX,XXX,XXX (손익 +₩X,XXX,XXX / +X.X%)
        1일 변동: +₩XXX,XXX (+X.X%)
        1주 변동: +₩X,XXX,XXX (+X.X%)
        1개월 변동: +₩XX,XXX,XXX (+X.X%)
        종목별 수익률 순위: NVDA +25.3% > GOOGL +18.1% > ... > PLTR -5.2%
    """
    history = load_history()
    if not history:
        return "포트폴리오 히스토리 없음 (python3 portfolio_tracker.py --snapshot 실행 필요)"

    latest = history[-1]
    total = latest['total_krw']
    pnl = latest['total_pnl_krw']
    pnl_pct = latest['total_pnl_pct']

    lines = ["[포트폴리오 성과]"]
    lines.append(f"총 평가: ₩{total:,} (손익 {'+' if pnl>=0 else ''}₩{pnl:,} / "
                 f"{'+' if pnl_pct>=0 else ''}{pnl_pct}%)")

    # 기간별 변동
    for label, days in [("1일", 1), ("1주", 5), ("1개월", 22), ("3개월", 66)]:
        if len(history) > days:
            prev = history[-(days + 1)]
            delta = total - prev['total_krw']
            delta_pct = round(delta / prev['total_krw'] * 100, 2) if prev['total_krw'] else 0
            sign = '+' if delta >= 0 else ''
            lines.append(f"{label} 변동: {sign}₩{delta:,} ({sign}{delta_pct}%)")

    # 종목별 수익률 순위
    tickers = latest.get('tickers', {})
    sorted_t = sorted(tickers.items(), key=lambda x: x[1].get('pnl_pct', 0), reverse=True)
    if sorted_t:
        parts = [f"{t} {'+' if d['pnl_pct']>=0 else ''}{d['pnl_pct']}%"
                 for t, d in sorted_t]
        lines.append(f"종목별: {' > '.join(parts)}")

    # 환율
    fx = latest.get('fx', {})
    if fx.get('USD'):
        lines.append(f"환율: USD/KRW {fx['USD']:,}")

    return '\n'.join(lines)


def format_history(n_days: int = 10) -> str:
    """최근 N일 히스토리 테이블."""
    history = load_history()
    if not history:
        return "히스토리 없음"

    recent = history[-n_days:]
    lines = [
        f"{'날짜':<12} {'총 평가':>14} {'일 변동':>12} {'일 변동%':>8} {'누적 손익':>14} {'누적%':>8}",
        "-" * 72,
    ]

    for i, snap in enumerate(recent):
        total = snap['total_krw']
        pnl = snap['total_pnl_krw']
        pnl_pct = snap['total_pnl_pct']

        if i > 0:
            prev = recent[i - 1]
            day_delta = total - prev['total_krw']
            day_pct = round(day_delta / prev['total_krw'] * 100, 2) if prev['total_krw'] else 0
        else:
            day_delta = 0
            day_pct = 0.0

        sign_d = '+' if day_delta >= 0 else ''
        sign_p = '+' if pnl >= 0 else ''

        lines.append(
            f"{snap['date']:<12} ₩{total:>12,} {sign_d}₩{day_delta:>10,} "
            f"{sign_d}{day_pct:>6.1f}% {sign_p}₩{pnl:>12,} {sign_p}{pnl_pct:>6.1f}%"
        )

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='포트폴리오 성과 추적')
    parser.add_argument('--snapshot', action='store_true',
                        help='오늘 스냅샷 저장')
    parser.add_argument('--summary', action='store_true',
                        help='성과 요약 출력')
    parser.add_argument('--history', type=int, nargs='?', const=10,
                        help='최근 N일 히스토리')
    args = parser.parse_args()

    if args.snapshot:
        snap = take_snapshot()
        total = snap['total_krw']
        pnl = snap['total_pnl_krw']
        print(f"[OK] 스냅샷 저장: {snap['date']} ₩{total:,} (손익 ₩{pnl:,})")

    elif args.summary:
        print(format_summary())

    elif args.history is not None:
        print(format_history(args.history))

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
