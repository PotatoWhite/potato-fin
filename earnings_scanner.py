"""
실적 일정 스캐너 — 향후 7일 내 실적 발표 예정 종목 탐지.

데이터 소스:
1. yfinance: Ticker.calendar (미국 종목 안정)
2. 네이버 IR 스케줄 (한국 종목) — integration API 의 irScheduleInfo 활용 (있을 시)

출력: JSON Lines (한 종목당 한 줄)
사용처: run_earnings_preview.sh 에서 스캔 후 D-7 이내 종목에 프리뷰 생성
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    yf = None

STOCK_DIR = Path("/home/bravopotato/Spaces/finspace/potato-fin")
sys.path.insert(0, str(STOCK_DIR))


def get_portfolio_tickers() -> list[str]:
    """portfolio_db.py 로부터 보유 종목 티커 추출."""
    try:
        from portfolio_db import get_tickers
        return get_tickers()
    except Exception as e:
        print(f"[scanner] portfolio_db 로드 실패: {e}", file=sys.stderr)
        return []


def scan_yfinance(tickers: list[str], days_ahead: int = 14) -> list[dict]:
    """yfinance 로 earnings calendar 조회."""
    if yf is None:
        return []

    results = []
    today = datetime.now().date()
    cutoff = today + timedelta(days=days_ahead)

    for ticker in tickers:
        # 한국 종목은 네이버가 나음 (별도 처리)
        if ticker.endswith((".KS", ".KQ")):
            continue
        try:
            t = yf.Ticker(ticker)
            cal = t.calendar
            if not cal:
                continue

            # earnings_date 추출
            e_date = None
            if isinstance(cal, dict):
                dates = cal.get("Earnings Date")
                if isinstance(dates, list) and dates:
                    e_date = dates[0]
                elif isinstance(dates, str):
                    e_date = datetime.fromisoformat(dates).date()
                elif hasattr(dates, 'date'):
                    e_date = dates.date() if hasattr(dates, 'date') else dates
            if e_date is None:
                continue

            # timedelta-compatible
            if hasattr(e_date, 'date'):
                e_date = e_date.date()
            if not isinstance(e_date, (datetime.__base__,)) and not hasattr(e_date, 'year'):
                continue

            # D-day 계산
            if today <= e_date <= cutoff:
                dday = (e_date - today).days
                consensus_eps = cal.get("Earnings Average") if isinstance(cal, dict) else None
                consensus_rev = cal.get("Revenue Average") if isinstance(cal, dict) else None
                results.append({
                    "ticker": ticker,
                    "date": e_date.isoformat() if hasattr(e_date, 'isoformat') else str(e_date),
                    "dday": dday,
                    "consensus_eps": str(consensus_eps) if consensus_eps else None,
                    "consensus_rev": str(consensus_rev) if consensus_rev else None,
                    "source": "yfinance",
                })
        except Exception as e:
            # 조용히 skip
            pass

    return results


def scan_naver_kr(tickers: list[str], days_ahead: int = 14) -> list[dict]:
    """네이버 integration API 의 irScheduleInfo 활용 (한국 종목)."""
    import requests

    UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
    HEADERS = {"User-Agent": UA, "Referer": "https://m.stock.naver.com/"}

    results = []
    today = datetime.now().date()
    cutoff = today + timedelta(days=days_ahead)

    for ticker in tickers:
        if not ticker.endswith((".KS", ".KQ")):
            continue
        code = ticker.split(".")[0]
        try:
            r = requests.get(f"https://m.stock.naver.com/api/stock/{code}/integration",
                             headers=HEADERS, timeout=10)
            r.raise_for_status()
            data = r.json()
            ir_info = data.get("irScheduleInfo") or {}
            # 네이버 IR 스케줄 구조는 가변적이라 보수적 파싱
            events = ir_info.get("irScheduleList") or []
            for event in events:
                event_date_str = event.get("eventDate") or event.get("date")
                if not event_date_str:
                    continue
                try:
                    e_date = datetime.strptime(event_date_str[:10], "%Y-%m-%d").date()
                except Exception:
                    continue
                if today <= e_date <= cutoff:
                    # 실적 관련 이벤트만
                    etype = str(event.get("eventType") or event.get("type") or "").lower()
                    ename = str(event.get("eventName") or event.get("title") or "")
                    if "실적" in ename or "earning" in etype or "report" in etype:
                        dday = (e_date - today).days
                        results.append({
                            "ticker": ticker,
                            "date": e_date.isoformat(),
                            "dday": dday,
                            "event_name": ename,
                            "consensus_eps": None,
                            "consensus_rev": None,
                            "source": "naver",
                        })
        except Exception:
            pass

    return results


def main():
    tickers = get_portfolio_tickers()
    if not tickers:
        # fallback: 하드코드 (19종목)
        tickers = [
            "005930.KS", "000660.KS", "035420.KS", "195940.KQ", "429760.KS",
            "1377.T", "BAYN.DE",
            "GOOGL", "MSFT", "NVDA", "TSLA", "UNH", "WRB", "PLTR", "QCOM",
            "XOM", "CVX", "SLV", "BOTZ",
        ]

    results = scan_yfinance(tickers) + scan_naver_kr(tickers)
    # dday 오름차순 정렬
    results.sort(key=lambda x: x.get("dday", 999))

    # JSON Lines 출력
    for r in results:
        print(json.dumps(r, ensure_ascii=False))

    # 요약 stderr
    print(f"[scanner] 향후 14일 내 실적: {len(results)}건", file=sys.stderr)
    for r in results[:5]:
        print(f"  D-{r['dday']:>2} {r['ticker']} ({r['date']})", file=sys.stderr)


if __name__ == "__main__":
    main()
