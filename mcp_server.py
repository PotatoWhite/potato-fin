#!/usr/bin/env python3
"""주식 포트폴리오 MCP 서버

Claude Code가 직접 주가/포트폴리오/환율/배당을 조회하고,
주가 업데이트를 실행하며, 보고서를 읽고, 매매 기록을 추가할 수 있다.
"""

import json
import os
import subprocess
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
from dateutil.relativedelta import relativedelta
from mcp.server.fastmcp import FastMCP

# === 경로 설정 ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRADE_FILE = os.path.join(BASE_DIR, "매매기록.xlsx")
EXCEL_FILE = os.path.join(BASE_DIR, "주식.xlsx")
REPORT_DIR = os.path.join(BASE_DIR, "보고서")
UPDATE_SCRIPT = os.path.join(BASE_DIR, "주가_업데이트.py")

SECTOR = {
    "035420.KS": "IT",
    "195940.KQ": "헬스케어",
    "429760.KS": "ETF/인덱스",
    "1377.T": "소비재",
    "BAYN.DE": "헬스케어",
    "BOTZ": "ETF/테마",
    "CRWV": "IT",
    "CVX": "에너지",
    "GOOGL": "IT",
    "MSFT": "IT",
    "NVDA": "IT",
    "PLTR": "IT",
    "QCOM": "IT",
    "SLV": "ETF/원자재",
    "TSLA": "자동차",
    "UNH": "헬스케어",
    "WRB": "금융",
    "XOM": "에너지",
}

mcp = FastMCP("stock-portfolio")


# === 핵심 함수 (주가_업데이트.py에서 복제 — 한글 파일명 import 불가) ===


def load_portfolio():
    """매매기록.xlsx에서 현재 포트폴리오 계산 (매수/매도 반영)"""
    df = pd.read_excel(TRADE_FILE, sheet_name="매매기록")
    holdings = {}
    for _, row in df.iterrows():
        ticker = row["티커"]
        if ticker not in holdings:
            holdings[ticker] = {
                "종목명": row["종목명"],
                "티커": ticker,
                "통화": row["통화"],
                "수량": 0,
                "매입금액": 0.0,
            }
        if row["매매구분"] == "매수":
            holdings[ticker]["수량"] += row["수량"]
            holdings[ticker]["매입금액"] += row["금액"]
        elif row["매매구분"] == "매도":
            h = holdings[ticker]
            if h["수량"] > 0:
                avg_cost = h["매입금액"] / h["수량"]
                h["수량"] -= row["수량"]
                h["매입금액"] = round(avg_cost * h["수량"], 2)
    portfolio = []
    for t, h in holdings.items():
        if h["수량"] > 0:
            portfolio.append(
                (h["종목명"], h["티커"], h["통화"], h["수량"], round(h["매입금액"], 2))
            )
    return portfolio


def fetch_prices(portfolio):
    """yfinance로 현재가 + 환율 조회"""
    tickers = [row[1] for row in portfolio]
    fx_pairs = ["USDKRW=X", "JPYKRW=X", "EURKRW=X"]
    data = yf.download(tickers + fx_pairs, period="1d", progress=False)
    prices = {}
    for name, ticker, *_ in portfolio:
        try:
            price = data["Close"][ticker].iloc[-1]
            if pd.notna(price):
                prices[ticker] = int(price) if price > 100 else round(float(price), 2)
            else:
                prices[ticker] = None
        except Exception:
            prices[ticker] = None
    fx_rates = {"KRW": 1.0}
    for pair, key in [("USDKRW=X", "USD"), ("JPYKRW=X", "JPY"), ("EURKRW=X", "EUR")]:
        try:
            fx_rates[key] = round(float(data["Close"][pair].iloc[-1]), 2)
        except Exception:
            fx_rates[key] = None
    return prices, fx_rates


# === MCP 도구 ===


@mcp.tool()
def get_stock_prices(tickers: str) -> str:
    """쉼표 구분 티커 목록의 현재가를 일괄 조회한다.

    Args:
        tickers: 쉼표로 구분된 티커 (예: "NVDA,TSLA,MSFT")
    """
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        return "티커를 입력하세요."
    data = yf.download(ticker_list, period="1d", progress=False)
    results = []
    for t in ticker_list:
        try:
            if len(ticker_list) == 1:
                price = data["Close"].iloc[-1]
            else:
                price = data["Close"][t].iloc[-1]
            if pd.notna(price):
                price_val = int(price) if price > 100 else round(float(price), 2)
                results.append({"ticker": t, "price": price_val})
            else:
                results.append({"ticker": t, "price": None, "error": "데이터 없음"})
        except Exception as e:
            results.append({"ticker": t, "price": None, "error": str(e)})
    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool()
def get_portfolio() -> str:
    """매매기록.xlsx에서 현재 포트폴리오를 계산하고 현재가/환율로 평가한다."""
    portfolio = load_portfolio()
    prices, fx_rates = fetch_prices(portfolio)

    rows = []
    for name, ticker, currency, qty, cost in portfolio:
        price = prices.get(ticker)
        if price is None:
            rows.append(
                {
                    "종목명": name,
                    "티커": ticker,
                    "통화": currency,
                    "수량": qty,
                    "매입금액": cost,
                    "현재가": None,
                    "error": "가격 조회 실패",
                }
            )
            continue
        valuation = round(price * qty, 2)
        pnl = round(valuation - cost, 2)
        pnl_pct = round(pnl / cost * 100, 2) if cost != 0 else 0
        rate = fx_rates.get(currency, 1.0)
        val_krw = round(valuation * rate) if rate else None
        pnl_krw = round(pnl * rate) if rate else None
        rows.append(
            {
                "종목명": name,
                "티커": ticker,
                "섹터": SECTOR.get(ticker, "기타"),
                "통화": currency,
                "현재가": price,
                "수량": qty,
                "매입금액": cost,
                "평가금액": valuation,
                "평가손익": pnl,
                "손익률(%)": pnl_pct,
                "환율": rate,
                "평가금액(원)": val_krw,
                "평가손익(원)": pnl_krw,
            }
        )

    total_val_krw = sum(r.get("평가금액(원)", 0) or 0 for r in rows)
    total_cost_krw = sum(
        round((r.get("매입금액", 0)) * (r.get("환율", 1) or 1)) for r in rows
    )
    total_pnl_krw = total_val_krw - total_cost_krw
    total_pct = round(total_pnl_krw / total_cost_krw * 100, 2) if total_cost_krw else 0

    result = {
        "기준시각": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "환율": {k: v for k, v in fx_rates.items() if k != "KRW"},
        "종목": rows,
        "총평가금액(원)": total_val_krw,
        "총매입금액(원)": total_cost_krw,
        "총평가손익(원)": total_pnl_krw,
        "총손익률(%)": total_pct,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def get_exchange_rates() -> str:
    """USD/KRW, JPY/KRW, EUR/KRW 환율을 조회한다."""
    pairs = ["USDKRW=X", "JPYKRW=X", "EURKRW=X"]
    data = yf.download(pairs, period="1d", progress=False)
    rates = {}
    for pair, label in [
        ("USDKRW=X", "USD/KRW"),
        ("JPYKRW=X", "JPY/KRW"),
        ("EURKRW=X", "EUR/KRW"),
    ]:
        try:
            rates[label] = round(float(data["Close"][pair].iloc[-1]), 2)
        except Exception:
            rates[label] = None
    return json.dumps(rates, ensure_ascii=False, indent=2)


@mcp.tool()
def get_dividends(tickers: str) -> str:
    """쉼표 구분 티커의 최근 12개월 배당 데이터를 조회한다.

    Args:
        tickers: 쉼표로 구분된 티커 (예: "MSFT,GOOGL")
    """
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    one_year_ago = datetime.now() - relativedelta(years=1)
    results = {}
    for t in ticker_list:
        try:
            tk = yf.Ticker(t)
            divs = tk.dividends
            if not divs.empty:
                recent = divs[divs.index >= one_year_ago.strftime("%Y-%m-%d")]
                annual_ps = round(float(recent.sum()), 4) if not recent.empty else 0
                last_div = round(float(divs.iloc[-1]), 4)
                last_date = divs.index[-1].strftime("%Y-%m-%d")
            else:
                annual_ps, last_div, last_date = 0, 0, "-"
        except Exception:
            annual_ps, last_div, last_date = 0, 0, "-"
        results[t] = {
            "연간배당(주당)": annual_ps,
            "최근배당(주당)": last_div,
            "최근배당일": last_date,
        }
    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool()
def run_price_update() -> str:
    """주가_업데이트.py를 실행하여 주식.xlsx에 새 시트를 추가하고 결과를 반환한다."""
    python = os.path.join(BASE_DIR, ".venv", "bin", "python3")
    if not os.path.exists(python):
        python = sys.executable
    try:
        result = subprocess.run(
            [python, UPDATE_SCRIPT],
            capture_output=True,
            text=True,
            cwd=BASE_DIR,
            timeout=120,
        )
        output = result.stdout
        if result.returncode != 0:
            output += f"\n[STDERR]\n{result.stderr}"
        return output
    except subprocess.TimeoutExpired:
        return "주가 업데이트 타임아웃 (120초 초과)"
    except Exception as e:
        return f"실행 오류: {e}"


@mcp.tool()
def get_report(date: str) -> str:
    """보고서/YYYY-MM-DD.md 파일을 읽어 반환한다.

    Args:
        date: 보고서 날짜 (YYYY-MM-DD). 미입력 시 가장 최근 보고서.
    """
    if date:
        path = os.path.join(REPORT_DIR, f"{date}.md")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return f"보고서 없음: {path}"

    # 날짜 미입력 시 가장 최근 보고서
    if not os.path.exists(REPORT_DIR):
        return "보고서 폴더가 없습니다."
    files = sorted(
        [f for f in os.listdir(REPORT_DIR) if f.endswith(".md")], reverse=True
    )
    if not files:
        return "보고서가 없습니다."
    path = os.path.join(REPORT_DIR, files[0])
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@mcp.tool()
def record_trade(
    종목명: str,
    티커: str,
    매매구분: str,
    수량: int,
    단가: float,
    통화: str,
    메모: str = "",
) -> str:
    """매매기록.xlsx에 매수/매도 기록을 추가한다.

    Args:
        종목명: 종목 이름 (예: "엔비디아")
        티커: 티커 심볼 (예: "NVDA")
        매매구분: "매수" 또는 "매도"
        수량: 거래 수량
        단가: 주당 가격
        통화: 통화 코드 (USD, KRW, JPY, EUR)
        메모: 메모 (선택)
    """
    if 매매구분 not in ("매수", "매도"):
        return "매매구분은 '매수' 또는 '매도'만 가능합니다."
    if 수량 <= 0:
        return "수량은 양수여야 합니다."
    if 단가 <= 0:
        return "단가는 양수여야 합니다."

    금액 = round(단가 * 수량, 2)
    new_row = {
        "날짜": datetime.now().strftime("%Y-%m-%d"),
        "종목명": 종목명,
        "티커": 티커,
        "매매구분": 매매구분,
        "수량": 수량,
        "단가": 단가,
        "금액": 금액,
        "통화": 통화,
        "메모": 메모,
    }

    df = pd.read_excel(TRADE_FILE, sheet_name="매매기록")
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_excel(TRADE_FILE, sheet_name="매매기록", index=False)

    return json.dumps(
        {"status": "OK", "message": f"{종목명} {매매구분} {수량}주 @ {단가} {통화} 기록 완료", "record": new_row},
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    mcp.run()
