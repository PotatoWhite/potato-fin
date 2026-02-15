#!/usr/bin/env python3
"""시장 데이터 + 종목 검증 데이터 + 펀더멘탈 점수

보고서 생성 전 실행하여 정확한 수치를 Claude에게 전달한다.
- 시장 지수/원자재/암호화폐/국채/환율
- 보유 종목별 공매도/기관보유/내부자거래
- 펀더멘탈 점수 (-5 ~ +5)
- 숨은진주 후보 검증용 데이터
"""

import json
import os
import sys
from datetime import datetime

import pandas as pd
import yfinance as yf

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_portfolio_tickers():
    """SQLite에서 보유 종목 티커 추출"""
    from portfolio_db import get_tickers
    return get_tickers()


def fetch_market_data():
    """시장 지수/원자재/암호화폐/국채/환율 조회"""
    tickers = {
        "^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow Jones",
        "^KS11": "KOSPI", "^KQ11": "KOSDAQ", "^N225": "Nikkei 225",
        "^GDAXI": "DAX", "^STOXX50E": "Euro STOXX 50",
        "GC=F": "Gold", "SI=F": "Silver", "CL=F": "WTI", "BZ=F": "Brent",
        "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum",
        "^VIX": "VIX",
        "^TNX": "10Y Treasury", "^TYX": "30Y Treasury",
        "^FVX": "5Y Treasury", "^IRX": "13W Treasury",
        "USDKRW=X": "USD/KRW", "USDJPY=X": "USD/JPY", "EURUSD=X": "EUR/USD",
        "JPYKRW=X": "JPY/KRW", "EURKRW=X": "EUR/KRW",
    }

    data = yf.download(list(tickers.keys()), period="5d", progress=False)
    results = []
    for ticker, name in tickers.items():
        try:
            col = data["Close"][ticker].dropna()
            if not col.empty:
                val = float(col.iloc[-1])
                date = col.index[-1].strftime("%m/%d")
                results.append(f"  {name:20s} | {val:>12,.2f} | {date}")
        except Exception:
            pass
    return results


def fetch_stock_detail(ticker):
    """종목별 공매도/기관보유/내부자거래/밸류에이션 조회"""
    t = yf.Ticker(ticker)
    info = t.info

    detail = {
        "ticker": ticker,
        "name": info.get("shortName", "N/A"),
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "market_cap_B": round(info.get("marketCap", 0) / 1e9, 1),
        "pe_ttm": info.get("trailingPE"),
        "pe_fwd": info.get("forwardPE"),
        "short_pct": info.get("shortPercentOfFloat"),
        "short_shares": info.get("sharesShort"),
        "inst_pct": info.get("heldPercentInstitutions"),
        "insider_pct": info.get("heldPercentInsiders"),
        "week52_high": info.get("fiftyTwoWeekHigh"),
        "week52_low": info.get("fiftyTwoWeekLow"),
        "dividend_yield": info.get("dividendYield"),
        "beta": info.get("beta"),
    }

    # 내부자 거래 최근 8건
    insider_txns = []
    try:
        insiders = t.insider_transactions
        if insiders is not None and not insiders.empty:
            for _, row in insiders.head(8).iterrows():
                txn_type = str(row.get("Transaction", ""))
                text = row.get("Text", "")
                if "Purchase" in str(text) or "Buy" in str(text):
                    direction = "BUY"
                elif "Sale" in str(text) or "Sell" in str(text):
                    direction = "SELL"
                elif "purchase" in txn_type.lower() or "buy" in txn_type.lower():
                    direction = "BUY"
                elif "sale" in txn_type.lower() or "sell" in txn_type.lower():
                    direction = "SELL"
                else:
                    direction = txn_type[:20] if txn_type else "UNKNOWN"

                insider_txns.append({
                    "date": str(row.get("Start Date", ""))[:10],
                    "insider": str(row.get("Insider", ""))[:40],
                    "direction": direction,
                    "shares": int(row.get("Shares", 0)) if pd.notna(row.get("Shares")) else 0,
                    "value": str(row.get("Value", "")),
                })
    except Exception:
        pass

    detail["insider_transactions"] = insider_txns
    return detail


def calc_fundamental_score(ticker):
    """현재 시점 펀더멘탈 점수 계산 (-5 ~ +5)

    구성 요소:
    1. 밸류에이션 (PEG, Forward P/E): -2 ~ +2
    2. 성장 모멘텀 (매출/EPS 성장률): -1.5 ~ +1.5
    3. 재무 건전성 (유동비율, FCF): -1 ~ +1
    4. 내부자/공매도 신호: -1.5 ~ +1.5
    5. 애널리스트 센티먼트: -1 ~ +1
    """
    t = yf.Ticker(ticker)
    info = t.info
    score = 0
    details = []
    raw = {}

    # === 1. 밸류에이션 (-2 ~ +2) ===
    peg = info.get("trailingPegRatio")
    pe_fwd = info.get("forwardPE")
    pe_ttm = info.get("trailingPE")
    raw["peg"] = peg
    raw["pe_fwd"] = pe_fwd

    if pe_ttm is not None and pe_ttm < 0:
        score -= 1.5
        details.append("적자(P/E<0)(-1.5)")
    elif peg is not None and peg > 0:
        if peg < 0.5:
            score += 2; details.append(f"PEG {peg:.2f} 극저(+2)")
        elif peg < 1.0:
            score += 1; details.append(f"PEG {peg:.2f} 저평가(+1)")
        elif peg > 3.0:
            score -= 1; details.append(f"PEG {peg:.2f} 고평가(-1)")
    elif pe_fwd is not None:
        if pe_fwd < 12:
            score += 1.5; details.append(f"Fwd P/E {pe_fwd:.1f} 저(+1.5)")
        elif pe_fwd < 20:
            score += 0.5; details.append(f"Fwd P/E {pe_fwd:.1f} 적정(+0.5)")
        elif pe_fwd > 60:
            score -= 1.5; details.append(f"Fwd P/E {pe_fwd:.1f} 극고(-1.5)")
        elif pe_fwd > 40:
            score -= 1; details.append(f"Fwd P/E {pe_fwd:.1f} 고(-1)")

    # === 2. 성장 모멘텀 (-1.5 ~ +1.5) ===
    rev_growth = info.get("revenueGrowth")
    earn_growth = info.get("earningsGrowth")
    raw["rev_growth"] = rev_growth
    raw["earn_growth"] = earn_growth

    if rev_growth is not None:
        if rev_growth > 0.30:
            score += 1; details.append(f"매출성장 {rev_growth*100:.0f}%(+1)")
        elif rev_growth > 0.10:
            score += 0.5; details.append(f"매출성장 {rev_growth*100:.0f}%(+0.5)")
        elif rev_growth < -0.05:
            score -= 1; details.append(f"매출역성장 {rev_growth*100:.0f}%(-1)")

    if earn_growth is not None:
        if earn_growth > 0.30:
            score += 0.5; details.append(f"이익성장 {earn_growth*100:.0f}%(+0.5)")
        elif earn_growth < -0.10:
            score -= 0.5; details.append(f"이익역성장 {earn_growth*100:.0f}%(-0.5)")

    # === 3. 재무 건전성 (-1 ~ +1) ===
    current_ratio = info.get("currentRatio")
    fcf = info.get("freeCashflow")
    raw["current_ratio"] = current_ratio
    raw["fcf_B"] = round(fcf / 1e9, 1) if fcf else None

    health_score = 0
    if current_ratio is not None:
        if current_ratio > 2:
            health_score += 0.5
        elif current_ratio < 0.8:
            health_score -= 0.5

    if fcf is not None:
        if fcf > 0:
            health_score += 0.5
        else:
            health_score -= 0.5

    if health_score != 0:
        score += health_score
        details.append(f"재무건전 {health_score:+.1f}(유동{current_ratio or 'N/A'}/FCF{raw['fcf_B'] or 'N/A'}B)")

    # === 4. 내부자/공매도 신호 (-1.5 ~ +1.5) ===
    short_pct = info.get("shortPercentOfFloat")
    raw["short_pct"] = short_pct

    if short_pct is not None:
        sp = short_pct * 100 if short_pct < 1 else short_pct
        if sp >= 20:
            score -= 1; details.append(f"공매도 {sp:.1f}% 극고(-1)")
        elif sp >= 10:
            score -= 0.5; details.append(f"공매도 {sp:.1f}% 고(-0.5)")
        elif sp < 2:
            score += 0.5; details.append(f"공매도 {sp:.1f}% 저(+0.5)")

    # 내부자 거래
    try:
        insiders = t.insider_transactions
        if insiders is not None and not insiders.empty:
            recent = insiders.head(10)
            buys = 0
            sells = 0
            for _, row in recent.iterrows():
                text = str(row.get("Text", "")) + str(row.get("Transaction", ""))
                if "purchase" in text.lower() or "buy" in text.lower():
                    buys += 1
                elif "sale" in text.lower() or "sell" in text.lower():
                    sells += 1
            raw["insider_buys"] = buys
            raw["insider_sells"] = sells
            if buys > sells and buys >= 2:
                score += 1; details.append(f"내부자 매수{buys}>매도{sells}(+1)")
            elif buys > 0 and buys > sells:
                score += 0.5; details.append(f"내부자 매수{buys}>매도{sells}(+0.5)")
            elif sells >= 3 and buys == 0:
                score -= 1; details.append(f"내부자 매도만{sells}건(-1)")
            elif sells > buys and sells >= 2:
                score -= 0.5; details.append(f"내부자 매도{sells}>매수{buys}(-0.5)")
    except Exception:
        pass

    # === 5. 애널리스트 센티먼트 (-1 ~ +1) ===
    rec_key = info.get("recommendationKey", "")
    rec_mean = info.get("recommendationMean")
    target_mean = info.get("targetMeanPrice")
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    raw["rec_key"] = rec_key
    raw["target_mean"] = target_mean

    if rec_mean is not None:
        if rec_mean <= 1.5:
            score += 1; details.append(f"애널리스트 Strong Buy({rec_mean:.1f})(+1)")
        elif rec_mean <= 2.2:
            score += 0.5; details.append(f"애널리스트 Buy({rec_mean:.1f})(+0.5)")
        elif rec_mean >= 3.5:
            score -= 1; details.append(f"애널리스트 Sell({rec_mean:.1f})(-1)")

    # 목표가 괴리
    if target_mean and price and price > 0:
        upside = (target_mean - price) / price * 100
        raw["upside_pct"] = round(upside, 1)
        if upside > 40:
            score += 0.5; details.append(f"목표가 괴리 +{upside:.0f}%(+0.5)")
        elif upside < -10:
            score -= 0.5; details.append(f"목표가 괴리 {upside:.0f}%(-0.5)")

    score = max(-5, min(5, round(score, 1)))

    if score >= 2:
        label = "강한 매수"
    elif score >= 1:
        label = "매수"
    elif score > 0:
        label = "약한 매수"
    elif score == 0:
        label = "중립"
    elif score > -1:
        label = "약한 매도"
    elif score > -2:
        label = "매도"
    else:
        label = "강한 매도"

    return {"score": score, "label": label, "details": details, "raw": raw}


def _score_label(score):
    """점수 → 라벨 변환"""
    if score >= 2:
        return "강한 매수"
    elif score >= 1:
        return "매수"
    elif score > 0:
        return "약한 매수"
    elif score == 0:
        return "중립"
    elif score > -1:
        return "약한 매도"
    elif score > -2:
        return "매도"
    else:
        return "강한 매도"


def calc_fundamental_score_v2(ticker):
    """펀더멘탈 점수 v2 (8 컴포넌트, -5 ~ +5)

    1. 밸류에이션 심화 [-2, +2]: PEG, Forward P/E vs 섹터, EV/EBITDA
    2. 수익성 추이 [-1.5, +1.5]: 영업이익률 5Q 추이, 순이익률, ROE
    3. 성장 모멘텀 [-1.5, +1.5]: 매출/EPS YoY, 연속 성장 분기
    4. 재무 건전성 [-1, +1]: FCF 추이, D/E, 유동비율
    5. 성장함정 체크 [-1, 0]: 매출성장+FCF적자+고부채
    6. 배당 건전성 [-0.5, +0.5]: 배당성향, 배당 성장
    7. 실적 서프라이즈 [-1, +1]: 최근 4Q Beat/Miss
    8. DCF 간이 평가 [-1, +1]: FCF 기반 간이 DCF vs 시총
    """
    t = yf.Ticker(ticker)
    info = t.info
    components = {}
    details = []

    # 분기 재무제표 조회
    try:
        qi = t.quarterly_income_stmt
    except Exception:
        qi = None
    try:
        qb = t.quarterly_balance_sheet
    except Exception:
        qb = None
    try:
        qc = t.quarterly_cashflow
    except Exception:
        qc = None

    # ETF 판별 (quoteType)
    is_etf = info.get("quoteType", "").upper() in ("ETF", "MUTUALFUND")

    # === 1. 밸류에이션 심화 [-2, +2] ===
    val_scores = []
    peg = info.get("trailingPegRatio")
    pe_fwd = info.get("forwardPE")
    pe_ttm = info.get("trailingPE")
    ev_ebitda = info.get("enterpriseToEbitda")

    if pe_ttm is not None and pe_ttm < 0:
        val_scores.append(-2)
        details.append(f"적자(P/E<0)")
    else:
        if peg is not None and peg > 0:
            if peg < 0.5:
                val_scores.append(2)
            elif peg < 1.0:
                val_scores.append(1)
            elif peg < 2.0:
                val_scores.append(0)
            else:
                val_scores.append(-1)

        if pe_fwd is not None and pe_fwd > 0:
            sector_pe = info.get("sectorPe") or info.get("industryPe")
            if sector_pe and sector_pe > 0:
                ratio = pe_fwd / sector_pe
                if ratio < 0.5:
                    val_scores.append(1)
                elif ratio > 1.5:
                    val_scores.append(-1)
                else:
                    val_scores.append(0)
            else:
                if pe_fwd < 12:
                    val_scores.append(1)
                elif pe_fwd > 40:
                    val_scores.append(-1)
                else:
                    val_scores.append(0)

        if ev_ebitda is not None and ev_ebitda > 0:
            if ev_ebitda < 8:
                val_scores.append(1)
            elif ev_ebitda <= 15:
                val_scores.append(0)
            elif ev_ebitda > 25:
                val_scores.append(-1)
            else:
                val_scores.append(0)

    if val_scores:
        val_avg = sum(val_scores) / len(val_scores)
        val_final = max(-2, min(2, round(val_avg, 1)))
    else:
        val_final = 0
    components["밸류에이션"] = val_final
    val_detail_parts = []
    if peg is not None:
        val_detail_parts.append(f"PEG {peg:.2f}")
    if ev_ebitda is not None:
        val_detail_parts.append(f"EV/EBITDA {ev_ebitda:.1f}x")
    if pe_fwd is not None:
        val_detail_parts.append(f"Fwd P/E {pe_fwd:.1f}")
    details.append(f"밸류에이션: {val_final:+.1f} ({', '.join(val_detail_parts) if val_detail_parts else 'N/A'})")

    # === 2. 수익성 추이 [-1.5, +1.5] ===
    profit_score = 0
    profit_parts = []
    if qi is not None and not qi.empty and not is_etf:
        cols = sorted(qi.columns, reverse=True)
        # 영업이익률 5Q 추이
        op_margins = []
        for col in cols[:5]:
            rev = qi.loc["Total Revenue", col] if "Total Revenue" in qi.index else None
            oi = qi.loc["Operating Income", col] if "Operating Income" in qi.index else None
            if pd.notna(rev) and pd.notna(oi) and rev > 0:
                op_margins.append(round(float(oi / rev * 100), 1))
        if len(op_margins) >= 3:
            op_margins_chrono = list(reversed(op_margins))
            improving = sum(1 for i in range(1, len(op_margins_chrono)) if op_margins_chrono[i] > op_margins_chrono[i-1])
            if improving >= len(op_margins_chrono) - 1:
                profit_score += 1
                profit_parts.append(f"영업이익률 개선 {'→'.join(str(m)+'%' for m in op_margins_chrono)}")
            elif improving == 0:
                profit_score -= 1
                profit_parts.append(f"영업이익률 악화 {'→'.join(str(m)+'%' for m in op_margins_chrono)}")

        # 순이익률 (최근 vs 전전분기)
        ni_key = "Net Income" if "Net Income" in qi.index else None
        if ni_key and len(cols) >= 3:
            ni_now = qi.loc[ni_key, cols[0]]
            rev_now = qi.loc["Total Revenue", cols[0]] if "Total Revenue" in qi.index else None
            ni_prev = qi.loc[ni_key, cols[2]]
            rev_prev = qi.loc["Total Revenue", cols[2]] if "Total Revenue" in qi.index else None
            if pd.notna(ni_now) and pd.notna(rev_now) and rev_now > 0:
                if pd.notna(ni_prev) and pd.notna(rev_prev) and rev_prev > 0:
                    m_now = ni_now / rev_now
                    m_prev = ni_prev / rev_prev
                    if m_prev <= 0 and m_now > 0:
                        profit_score += 1.5
                        profit_parts.append("흑자전환")
                    elif m_prev > 0 and m_now <= 0:
                        profit_score -= 1.5
                        profit_parts.append("적자전환")

        # ROE
        roe = info.get("returnOnEquity")
        if roe is not None:
            if roe > 0.20:
                profit_score += 0.5
                profit_parts.append(f"ROE {roe*100:.1f}%")
            elif roe < 0:
                profit_score -= 0.5
                profit_parts.append(f"ROE {roe*100:.1f}%")

    profit_score = max(-1.5, min(1.5, round(profit_score, 1)))
    components["수익성 추이"] = profit_score
    details.append(f"수익성 추이: {profit_score:+.1f} ({'; '.join(profit_parts) if profit_parts else 'N/A'})")

    # === 3. 성장 모멘텀 [-1.5, +1.5] ===
    growth_score = 0
    growth_parts = []
    rev_growth = info.get("revenueGrowth")
    earn_growth = info.get("earningsGrowth")

    if rev_growth is not None:
        if rev_growth > 0.30:
            growth_score += 1.5
        elif rev_growth > 0.10:
            growth_score += 1
        elif rev_growth > 0:
            growth_score += 0.5
        elif rev_growth < -0.05:
            growth_score -= 1
        growth_parts.append(f"매출YoY {rev_growth*100:.0f}%")

    if earn_growth is not None:
        if earn_growth > 0.30:
            growth_score += 0.5
        elif earn_growth < -0.20:
            growth_score -= 0.5
        growth_parts.append(f"EPS YoY {earn_growth*100:.0f}%")

    # 연속 성장 분기
    if qi is not None and not qi.empty and "Total Revenue" in qi.index:
        cols = sorted(qi.columns, reverse=True)
        consecutive = 0
        for i in range(len(cols) - 4):
            curr = cols[i]
            # 1년 전 분기 찾기
            target = curr - pd.DateOffset(years=1)
            yoy_q = None
            for q in cols:
                if abs((q - target).days) <= 45:
                    yoy_q = q
                    break
            if yoy_q is not None:
                r_now = qi.loc["Total Revenue", curr]
                r_prev = qi.loc["Total Revenue", yoy_q]
                if pd.notna(r_now) and pd.notna(r_prev) and r_prev > 0 and r_now > r_prev:
                    consecutive += 1
                else:
                    break
            else:
                break
        if consecutive >= 4:
            growth_score += 0.5
            growth_parts.append(f"{consecutive}Q 연속성장")

    growth_score = max(-1.5, min(1.5, round(growth_score, 1)))
    components["성장 모멘텀"] = growth_score
    details.append(f"성장 모멘텀: {growth_score:+.1f} ({', '.join(growth_parts) if growth_parts else 'N/A'})")

    # === 4. 재무 건전성 [-1, +1] ===
    health_score = 0
    health_parts = []
    if not is_etf:
        # FCF 추이 (최근 4Q)
        if qc is not None and not qc.empty and "Free Cash Flow" in qc.index:
            cf_cols = sorted(qc.columns, reverse=True)[:4]
            fcf_vals = [qc.loc["Free Cash Flow", c] for c in cf_cols if pd.notna(qc.loc["Free Cash Flow", c])]
            if fcf_vals:
                pos_count = sum(1 for v in fcf_vals if v > 0)
                if pos_count == len(fcf_vals):
                    health_score += 0.5
                    health_parts.append(f"FCF 양수 {pos_count}/{len(fcf_vals)}Q")
                elif pos_count == 0:
                    health_score -= 0.5
                    health_parts.append(f"FCF 적자 지속")

        # D/E ratio
        de = info.get("debtToEquity")
        if de is not None:
            de_ratio = de / 100 if de > 10 else de  # yfinance는 %로 줄 수 있음
            if de_ratio < 0.5:
                health_score += 0.5
                health_parts.append(f"D/E {de_ratio:.2f}")
            elif de_ratio > 2.0:
                health_score -= 0.5
                health_parts.append(f"D/E {de_ratio:.2f} 고부채")

        # 유동비율
        cr = info.get("currentRatio")
        if cr is not None:
            if cr > 2.0:
                health_score += 0.5
                health_parts.append(f"유동비율 {cr:.1f}")
            elif cr < 0.8:
                health_score -= 0.5
                health_parts.append(f"유동비율 {cr:.1f} 위험")

    health_score = max(-1, min(1, round(health_score, 1)))
    components["재무 건전성"] = health_score
    details.append(f"재무 건전성: {health_score:+.1f} ({', '.join(health_parts) if health_parts else 'ETF/N/A'})")

    # === 5. 성장함정 체크 [-1, 0] ===
    trap_score = 0
    trap_parts = []
    if not is_etf and rev_growth is not None and rev_growth > 0:
        fcf_val = info.get("freeCashflow")
        de_val = info.get("debtToEquity")
        de_r = (de_val / 100 if de_val and de_val > 10 else de_val) if de_val else None

        if fcf_val is not None and fcf_val < 0 and de_r is not None and de_r > 1.5:
            trap_score = -1.0
            trap_parts.append(f"매출성장+FCF적자+D/E>{de_r:.1f}")

        # 마진 악화 3Q 연속
        if qi is not None and not qi.empty:
            cols = sorted(qi.columns, reverse=True)
            margins = []
            for col in cols[:4]:
                rev = qi.loc["Total Revenue", col] if "Total Revenue" in qi.index else None
                oi = qi.loc["Operating Income", col] if "Operating Income" in qi.index else None
                if pd.notna(rev) and pd.notna(oi) and rev > 0:
                    margins.append(float(oi / rev))
            if len(margins) >= 4:
                margins_chrono = list(reversed(margins))
                declining = all(margins_chrono[i] < margins_chrono[i-1] for i in range(1, min(4, len(margins_chrono))))
                if declining and trap_score == 0:
                    trap_score = -0.5
                    trap_parts.append("마진 3Q 연속 악화")

    components["성장함정"] = trap_score
    if trap_score < 0:
        details.append(f"성장함정: {trap_score:+.1f} ({'; '.join(trap_parts)})")
    else:
        details.append(f"성장함정: 0 (해당 없음)")

    # === 6. 배당 건전성 [-0.5, +0.5] ===
    div_score = 0
    div_parts = []
    if not is_etf:
        payout = info.get("payoutRatio")
        div_yield = info.get("dividendYield")
        if payout is not None and div_yield is not None and div_yield > 0:
            if payout < 0.6:
                div_score = 0.5
                div_parts.append(f"배당성향 {payout*100:.0f}% 건전")
            elif payout > 1.0:
                div_score = -0.5
                div_parts.append(f"배당성향 {payout*100:.0f}% 초과지급")
        elif div_yield is None or div_yield == 0:
            div_parts.append("무배당")
    components["배당 건전성"] = div_score
    details.append(f"배당: {div_score:+.1f} ({', '.join(div_parts) if div_parts else 'N/A'})")

    # === 7. 실적 서프라이즈 [-1, +1] ===
    surprise_score = 0
    surprise_parts = []
    try:
        eh = t.earnings_history
        if eh is not None and not eh.empty:
            recent = eh.head(4)
            beats = 0
            misses = 0
            for _, row in recent.iterrows():
                surprise = row.get("epsActual", None)
                estimate = row.get("epsEstimate", None)
                if pd.notna(surprise) and pd.notna(estimate):
                    if surprise > estimate:
                        beats += 1
                    elif surprise < estimate:
                        misses += 1
            total_q = beats + misses
            if total_q > 0:
                if beats == total_q:
                    surprise_score = 1.0
                elif beats >= total_q * 0.75:
                    surprise_score = 0.5
                elif misses == total_q:
                    surprise_score = -1.0
                elif misses >= total_q * 0.75:
                    surprise_score = -0.5
                surprise_parts.append(f"Beat {beats}/{total_q}")
    except Exception:
        # earnings_history 미지원 시 earnings_dates 시도
        try:
            ed = t.earnings_dates
            if ed is not None and not ed.empty:
                # EPS Estimate vs Reported EPS 비교
                beats = 0
                misses = 0
                checked = 0
                for _, row in ed.iterrows():
                    est = row.get("EPS Estimate")
                    rep = row.get("Reported EPS")
                    if pd.notna(est) and pd.notna(rep):
                        if rep > est:
                            beats += 1
                        elif rep < est:
                            misses += 1
                        checked += 1
                    if checked >= 4:
                        break
                if checked > 0:
                    if beats == checked:
                        surprise_score = 1.0
                    elif beats >= checked * 0.75:
                        surprise_score = 0.5
                    elif misses == checked:
                        surprise_score = -1.0
                    elif misses >= checked * 0.75:
                        surprise_score = -0.5
                    surprise_parts.append(f"Beat {beats}/{checked}")
        except Exception:
            pass

    components["실적 Beat"] = surprise_score
    details.append(f"실적 Beat: {surprise_score:+.1f} ({', '.join(surprise_parts) if surprise_parts else 'N/A'})")

    # === 8. DCF 간이 평가 [-1, +1] ===
    dcf_score = 0
    dcf_parts = []
    if not is_etf:
        fcf = info.get("freeCashflow")
        mcap = info.get("marketCap")
        growth_r = rev_growth if rev_growth is not None else 0.05

        if fcf is not None and fcf > 0 and mcap is not None and mcap > 0:
            # 간이 DCF: FCF * (1+g) / (r - g), r=10%, g=growth capped 0~15%
            g = max(0.02, min(0.15, growth_r))
            r = 0.10
            if r > g:
                dcf_value = fcf * (1 + g) / (r - g)
                gap_pct = (dcf_value - mcap) / mcap * 100
                if gap_pct > 30:
                    dcf_score = 1.0
                    dcf_parts.append(f"DCF {gap_pct:+.0f}% 저평가")
                elif gap_pct < -30:
                    dcf_score = -1.0
                    dcf_parts.append(f"DCF {gap_pct:+.0f}% 고평가")
                else:
                    dcf_parts.append(f"DCF {gap_pct:+.0f}% 적정")

    components["DCF"] = dcf_score
    details.append(f"DCF: {dcf_score:+.1f} ({', '.join(dcf_parts) if dcf_parts else 'N/A'})")

    # === 종합 ===
    score = sum(components.values())
    score = max(-5, min(5, round(score, 1)))
    label = _score_label(score)

    return {
        "score": score,
        "label": label,
        "components": components,
        "details": details,
        "raw": {
            "peg": peg, "pe_fwd": pe_fwd, "ev_ebitda": ev_ebitda,
            "rev_growth": rev_growth, "earn_growth": earn_growth,
            "fcf_B": round(info.get("freeCashflow", 0) / 1e9, 1) if info.get("freeCashflow") else None,
            "de_ratio": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "roe": info.get("returnOnEquity"),
        },
    }


def calc_supply_demand_score(ticker):
    """수급 점수 계산 (-5 ~ +5)

    1. 기관 보유 [-1.5, +1.5]: 기관 보유율 수준
    2. 내부자 행동 [-2, +2]: 매수/매도 건수 + 금액 가중
    3. 공매도 상태 [-1.5, +1.5]: shortPercentOfFloat + 숏스퀴즈 보너스
    4. 셰이크아웃/분배 종합 [-1, +1]: 체크리스트 자동 판정
    5. 거래량 트렌드 [-0.5, +0.5]: 20일 vs 50일 평균 거래량
    """
    t = yf.Ticker(ticker)
    info = t.info
    components = {}
    details = []
    flags = {"shakeout": False, "distribution": False, "short_squeeze": False}

    is_etf = info.get("quoteType", "").upper() in ("ETF", "MUTUALFUND")

    # === 1. 기관 보유 [-1.5, +1.5] ===
    inst_score = 0
    inst_pct = info.get("heldPercentInstitutions")
    if inst_pct is not None and not is_etf:
        pct = inst_pct * 100 if inst_pct < 1 else inst_pct
        if pct > 80:
            inst_score = 1.0
        elif pct > 60:
            inst_score = 0.5
        elif pct < 40:
            inst_score = -0.5
        details.append(f"기관 보유: {inst_score:+.1f} ({pct:.1f}%)")
    else:
        details.append(f"기관 보유: 0 (N/A)")
    components["기관 보유"] = inst_score

    # === 2. 내부자 행동 [-2, +2] ===
    insider_score = 0
    insider_parts = []
    buys = 0
    sells = 0
    buy_value = 0
    sell_value = 0
    try:
        insiders = t.insider_transactions
        if insiders is not None and not insiders.empty:
            for _, row in insiders.head(10).iterrows():
                text = str(row.get("Text", "")) + str(row.get("Transaction", ""))
                val_str = str(row.get("Value", "0"))
                # 금액 파싱
                try:
                    val = float(val_str.replace(",", "").replace("$", ""))
                except (ValueError, TypeError):
                    val = 0

                if "purchase" in text.lower() or "buy" in text.lower():
                    buys += 1
                    buy_value += val
                elif "sale" in text.lower() or "sell" in text.lower():
                    sells += 1
                    sell_value += val

            # 기본 점수
            if buys >= 3 and sells == 0:
                insider_score = 2.0
                insider_parts.append(f"매수{buys}건, 매도0건 → 매우 강한 신호")
            elif buys > sells:
                insider_score = 1.0
                insider_parts.append(f"매수{buys}>매도{sells}")
            elif sells >= 3 and buys == 0:
                insider_score = -1.5
                insider_parts.append(f"매도만{sells}건 → 분배 위험")
            elif sells > buys:
                insider_score = -0.5
                insider_parts.append(f"매도{sells}>매수{buys}")

            # 금액 보너스
            if buy_value > 500000:
                insider_score = min(2, insider_score + 0.5)
                insider_parts.append(f"매수 ${buy_value/1e6:.1f}M 확신매수")
            if sell_value > 10000000:
                insider_score = max(-2, insider_score - 0.5)
                insider_parts.append(f"매도 ${sell_value/1e6:.1f}M 대규모")
    except Exception:
        insider_parts.append("데이터 없음")

    insider_score = max(-2, min(2, round(insider_score, 1)))
    components["내부자 행동"] = insider_score
    details.append(f"내부자 행동: {insider_score:+.1f} ({'; '.join(insider_parts) if insider_parts else 'N/A'})")

    # === 3. 공매도 상태 [-1.5, +1.5] ===
    short_score = 0
    short_pct = info.get("shortPercentOfFloat")
    short_parts = []
    if short_pct is not None and not is_etf:
        sp = short_pct * 100 if short_pct < 1 else short_pct
        if sp < 2:
            short_score = 1.0
            short_parts.append(f"{sp:.1f}% → 약세 베팅 거의 없음")
        elif sp < 5:
            short_score = 0.5
            short_parts.append(f"{sp:.1f}%")
        elif sp <= 10:
            short_score = 0
            short_parts.append(f"{sp:.1f}%")
        elif sp <= 20:
            short_score = -0.5
            short_parts.append(f"{sp:.1f}% 주의")
        else:
            short_score = -1.0
            short_parts.append(f"{sp:.1f}% 높음")

        # 숏스퀴즈 보너스: 공매도 >15% AND Beat 이력
        if sp > 15:
            try:
                ed = t.earnings_dates
                if ed is not None and not ed.empty:
                    for _, row in ed.iterrows():
                        est = row.get("EPS Estimate")
                        rep = row.get("Reported EPS")
                        if pd.notna(est) and pd.notna(rep) and rep > est:
                            short_score += 0.5
                            short_parts.append("숏스퀴즈 후보(Beat+고공매도)")
                            flags["short_squeeze"] = True
                            break
            except Exception:
                pass
    else:
        short_parts.append("N/A")

    short_score = max(-1.5, min(1.5, round(short_score, 1)))
    components["공매도"] = short_score
    details.append(f"공매도: {short_score:+.1f} ({'; '.join(short_parts)})")

    # === 4. 셰이크아웃/분배 종합 [-1, +1] ===
    sd_score = 0
    if not is_etf:
        sp_val = (short_pct * 100 if short_pct and short_pct < 1 else (short_pct or 50)) if short_pct else 50
        inst_val = (inst_pct * 100 if inst_pct and inst_pct < 1 else (inst_pct or 0)) if inst_pct else 0

        # 셰이크아웃: 공매도 <3% + 기관 >60% + 내부자 매도 없음(or 매수 있음)
        if sp_val < 3 and inst_val > 60 and sells <= buys:
            sd_score = 1.0
            flags["shakeout"] = True
            details.append(f"셰이크아웃: +1.0 (공매도<3% + 기관{inst_val:.0f}% + 내부자 OK)")
        # 분배: 내부자 매도만 + 공매도 >10% + 기관 감소 징후
        elif sells >= 3 and buys == 0 and sp_val > 10:
            sd_score = -1.0
            flags["distribution"] = True
            details.append(f"분배: -1.0 (내부자 매도만{sells}건 + 공매도{sp_val:.1f}%)")
        else:
            details.append(f"셰이크아웃/분배: 0 (조건 미충족)")
    else:
        details.append(f"셰이크아웃/분배: 0 (ETF)")

    components["셰이크아웃/분배"] = sd_score

    # === 5. 거래량 트렌드 [-0.5, +0.5] ===
    vol_score = 0
    try:
        hist = t.history(period="3mo")
        if hist is not None and not hist.empty and "Volume" in hist.columns:
            vol = hist["Volume"].dropna()
            if len(vol) >= 50:
                avg_20 = vol.iloc[-20:].mean()
                avg_50 = vol.iloc[-50:].mean()
                if avg_50 > 0:
                    ratio = avg_20 / avg_50
                    if ratio > 1.5:
                        vol_score = 0.5
                        details.append(f"거래량 트렌드: +0.5 (20d/50d={ratio:.2f}x 관심 증가)")
                    elif ratio < 0.7:
                        vol_score = -0.5
                        details.append(f"거래량 트렌드: -0.5 (20d/50d={ratio:.2f}x 관심 감소)")
                    else:
                        details.append(f"거래량 트렌드: 0 (20d/50d={ratio:.2f}x)")
                else:
                    details.append(f"거래량 트렌드: 0 (데이터 부족)")
            else:
                details.append(f"거래량 트렌드: 0 (데이터 부족)")
        else:
            details.append(f"거래량 트렌드: 0 (N/A)")
    except Exception:
        details.append(f"거래량 트렌드: 0 (조회 실패)")
    components["거래량 트렌드"] = vol_score

    # === 종합 ===
    score = sum(components.values())
    score = max(-5, min(5, round(score, 1)))
    label = _score_label(score)

    # 판정 라벨
    if flags["shakeout"]:
        verdict = "셰이크아웃"
    elif flags["distribution"]:
        verdict = "분배"
    elif flags["short_squeeze"]:
        verdict = "숏스퀴즈 후보"
    else:
        verdict = "중립"

    return {
        "score": score,
        "label": label,
        "verdict": verdict,
        "components": components,
        "details": details,
        "flags": flags,
    }


def calc_comprehensive_score(tech_score, fund_score, sd_score, sent_score):
    """종합 점수: 4개 점수 가중 합산 (-5 ~ +5)

    가중치:
    - 기술적: 35% (단기 타이밍)
    - 펀더멘탈: 30% (중장기 체력)
    - 수급: 25% (스마트머니 방향)
    - 센티먼트: 10% (노이즈 많으므로 낮은 비중)
    """
    raw = (tech_score * 0.35 + fund_score * 0.30 +
           sd_score * 0.25 + sent_score * 0.10)
    score = max(-5, min(5, round(raw, 1)))

    # 특수 라벨
    special = []
    if sd_score > 2.5 and tech_score < 0:
        special.append("셰이크아웃")
    if sd_score < -2.0 and sent_score > 1.0:
        special.append("분배 위험")

    label = _score_label(score)
    if special:
        label += " ⚠️" + "/".join(special)

    return {"score": score, "label": label, "special": special}


def calc_historical_fundamental_score(ticker, as_of_date):
    """특정 날짜 기준 펀더멘탈 점수 (-5 ~ +5)

    과거 분기 재무제표를 사용하여 해당 시점에 알 수 있었던 데이터만으로 계산.
    분기 실적은 분기종료 후 45일 뒤에 공시된다고 가정.

    구성 요소:
    1. 성장 모멘텀 (매출 YoY / EPS YoY): -2 ~ +2
    2. 재무 건전성 (유동비율, FCF): -1 ~ +1
    3. 내부자 거래 신호: -1.5 ~ +1.5
    4. 애널리스트 추천 변화: -1 ~ +1
    """
    from datetime import timedelta

    t = yf.Ticker(ticker)
    score = 0
    details = []

    # 분기 재무제표에서 as_of_date 기준 사용 가능한 분기 찾기
    # 실적 공시는 분기 종료 후 약 45일
    REPORT_DELAY = timedelta(days=45)

    try:
        qi = t.quarterly_income_stmt
        qb = t.quarterly_balance_sheet
        qc = t.quarterly_cashflow
    except Exception:
        qi = qb = qc = None

    # === 1. 성장 모멘텀 (-2 ~ +2) ===
    if qi is not None and not qi.empty:
        # as_of_date 기준 공시 가능한 분기들 (quarter_end + 45d <= as_of_date)
        available_qs = [col for col in qi.columns
                        if col + REPORT_DELAY <= pd.Timestamp(as_of_date)]
        available_qs = sorted(available_qs, reverse=True)

        if len(available_qs) >= 1:
            latest_q = available_qs[0]

            # 같은 분기 전년도 찾기 (YoY 비교)
            target_year = latest_q - pd.DateOffset(years=1)
            yoy_q = None
            for q in qi.columns:
                if abs((q - target_year).days) <= 45:
                    yoy_q = q
                    break

            # 매출 YoY
            if yoy_q is not None and "Total Revenue" in qi.index:
                rev_now = qi.loc["Total Revenue", latest_q]
                rev_prev = qi.loc["Total Revenue", yoy_q]
                if pd.notna(rev_now) and pd.notna(rev_prev) and rev_prev > 0:
                    rev_growth = (rev_now - rev_prev) / rev_prev
                    if rev_growth > 0.30:
                        score += 1; details.append(f"매출YoY {rev_growth*100:.0f}%(+1)")
                    elif rev_growth > 0.10:
                        score += 0.5; details.append(f"매출YoY {rev_growth*100:.0f}%(+0.5)")
                    elif rev_growth < -0.05:
                        score -= 1; details.append(f"매출YoY {rev_growth*100:.0f}%(-1)")

            # EPS YoY
            eps_key = "Diluted EPS" if "Diluted EPS" in qi.index else "Basic EPS"
            if yoy_q is not None and eps_key in qi.index:
                eps_now = qi.loc[eps_key, latest_q]
                eps_prev = qi.loc[eps_key, yoy_q]
                if pd.notna(eps_now) and pd.notna(eps_prev) and eps_prev != 0:
                    if eps_prev > 0:
                        eps_growth = (eps_now - eps_prev) / eps_prev
                    else:
                        eps_growth = 1.0 if eps_now > eps_prev else -1.0
                    if eps_growth > 0.30:
                        score += 1; details.append(f"EPS YoY {eps_growth*100:.0f}%(+1)")
                    elif eps_growth > 0.10:
                        score += 0.5; details.append(f"EPS YoY {eps_growth*100:.0f}%(+0.5)")
                    elif eps_now < 0:
                        score -= 1.5; details.append(f"EPS 적자(-1.5)")
                    elif eps_growth < -0.10:
                        score -= 0.5; details.append(f"EPS YoY {eps_growth*100:.0f}%(-0.5)")

    # === 2. 재무 건전성 (-1 ~ +1) ===
    if qb is not None and not qb.empty:
        available_bs = [col for col in qb.columns
                        if col + REPORT_DELAY <= pd.Timestamp(as_of_date)]
        available_bs = sorted(available_bs, reverse=True)

        if available_bs:
            latest_bs = available_bs[0]
            ca = qb.loc["Current Assets", latest_bs] if "Current Assets" in qb.index else None
            cl = qb.loc["Current Liabilities", latest_bs] if "Current Liabilities" in qb.index else None

            if pd.notna(ca) and pd.notna(cl) and cl > 0:
                cr = ca / cl
                if cr > 2:
                    score += 0.5; details.append(f"유동비율 {cr:.1f}(+0.5)")
                elif cr < 0.8:
                    score -= 0.5; details.append(f"유동비율 {cr:.1f}(-0.5)")

    if qc is not None and not qc.empty:
        available_cf = [col for col in qc.columns
                        if col + REPORT_DELAY <= pd.Timestamp(as_of_date)]
        available_cf = sorted(available_cf, reverse=True)

        if available_cf:
            latest_cf = available_cf[0]
            fcf = qc.loc["Free Cash Flow", latest_cf] if "Free Cash Flow" in qc.index else None

            if pd.notna(fcf):
                if fcf > 0:
                    score += 0.5; details.append(f"FCF {fcf/1e9:.1f}B(+0.5)")
                else:
                    score -= 0.5; details.append(f"FCF {fcf/1e9:.1f}B(-0.5)")

    # === 3. 내부자 거래 (-1.5 ~ +1.5) ===
    try:
        insiders = t.insider_transactions
        if insiders is not None and not insiders.empty:
            # as_of_date 이전의 내부자 거래만 (최근 90일)
            cutoff = pd.Timestamp(as_of_date) - timedelta(days=90)
            recent = []
            for _, row in insiders.iterrows():
                txn_date = pd.Timestamp(row.get("Start Date", ""))
                if pd.notna(txn_date) and cutoff <= txn_date <= pd.Timestamp(as_of_date):
                    recent.append(row)

            buys = 0
            sells = 0
            for row in recent[:10]:
                text = str(row.get("Text", "")) + str(row.get("Transaction", ""))
                if "purchase" in text.lower() or "buy" in text.lower():
                    buys += 1
                elif "sale" in text.lower() or "sell" in text.lower():
                    sells += 1

            if buys > sells and buys >= 2:
                score += 1; details.append(f"내부자 매수{buys}>매도{sells}(+1)")
            elif buys > 0 and buys > sells:
                score += 0.5; details.append(f"내부자 매수{buys}>매도{sells}(+0.5)")
            elif sells >= 3 and buys == 0:
                score -= 1; details.append(f"내부자 매도만{sells}건(-1)")
            elif sells > buys and sells >= 2:
                score -= 0.5; details.append(f"내부자 매도{sells}>매수{buys}(-0.5)")
    except Exception:
        pass

    # === 4. 애널리스트 추천 (-1 ~ +1) ===
    try:
        rec = t.recommendations
        if rec is not None and not rec.empty:
            # recommendations는 0m(이번달), -1m, -2m 등으로 제공
            # 가장 최근 데이터 사용
            row = rec.iloc[0]
            strong_buy = row.get("strongBuy", 0) or 0
            buy = row.get("buy", 0) or 0
            hold = row.get("hold", 0) or 0
            sell = row.get("sell", 0) or 0
            strong_sell = row.get("strongSell", 0) or 0
            total = strong_buy + buy + hold + sell + strong_sell

            if total > 0:
                weighted = (1 * strong_buy + 2 * buy + 3 * hold + 4 * sell + 5 * strong_sell) / total
                if weighted <= 1.5:
                    score += 1; details.append(f"애널리스트 Strong Buy({weighted:.1f})(+1)")
                elif weighted <= 2.2:
                    score += 0.5; details.append(f"애널리스트 Buy({weighted:.1f})(+0.5)")
                elif weighted >= 3.5:
                    score -= 1; details.append(f"애널리스트 Sell({weighted:.1f})(-1)")
    except Exception:
        pass

    score = max(-5, min(5, round(score, 1)))

    if score >= 2:
        label = "강한 매수"
    elif score >= 1:
        label = "매수"
    elif score > 0:
        label = "약한 매수"
    elif score == 0:
        label = "중립"
    elif score > -1:
        label = "약한 매도"
    elif score > -2:
        label = "매도"
    else:
        label = "강한 매도"

    return {"score": score, "label": label, "details": details}


def prefetch_historical_data(ticker):
    """백테스트용 과거 재무제표 일괄 조회 (API 호출 최소화)"""
    t = yf.Ticker(ticker)
    data = {"qi": None, "qb": None, "qc": None, "insiders": None, "rec": None}
    try:
        data["qi"] = t.quarterly_income_stmt
    except Exception:
        pass
    try:
        data["qb"] = t.quarterly_balance_sheet
    except Exception:
        pass
    try:
        data["qc"] = t.quarterly_cashflow
    except Exception:
        pass
    try:
        data["insiders"] = t.insider_transactions
    except Exception:
        pass
    try:
        data["rec"] = t.recommendations
    except Exception:
        pass
    return data


def calc_historical_fund_score_fast(prefetched, as_of_date):
    """미리 조회한 데이터로 특정 날짜 기준 펀더멘탈 점수 계산 (빠른 버전)"""
    from datetime import timedelta
    REPORT_DELAY = timedelta(days=45)

    qi = prefetched.get("qi")
    qb = prefetched.get("qb")
    qc = prefetched.get("qc")
    insiders = prefetched.get("insiders")
    rec = prefetched.get("rec")

    score = 0

    # 1. 성장 모멘텀 (-2 ~ +2)
    if qi is not None and not qi.empty:
        available_qs = sorted(
            [c for c in qi.columns if c + REPORT_DELAY <= pd.Timestamp(as_of_date)],
            reverse=True
        )
        if available_qs:
            latest_q = available_qs[0]
            target_year = latest_q - pd.DateOffset(years=1)
            yoy_q = None
            for q in qi.columns:
                if abs((q - target_year).days) <= 45:
                    yoy_q = q
                    break

            if yoy_q is not None and "Total Revenue" in qi.index:
                rev_now = qi.loc["Total Revenue", latest_q]
                rev_prev = qi.loc["Total Revenue", yoy_q]
                if pd.notna(rev_now) and pd.notna(rev_prev) and rev_prev > 0:
                    rg = (rev_now - rev_prev) / rev_prev
                    if rg > 0.30: score += 1
                    elif rg > 0.10: score += 0.5
                    elif rg < -0.05: score -= 1

            eps_key = "Diluted EPS" if "Diluted EPS" in qi.index else "Basic EPS"
            if yoy_q is not None and eps_key in qi.index:
                eps_now = qi.loc[eps_key, latest_q]
                eps_prev = qi.loc[eps_key, yoy_q]
                if pd.notna(eps_now) and pd.notna(eps_prev) and eps_prev != 0:
                    eg = (eps_now - eps_prev) / abs(eps_prev) if eps_prev > 0 else (1.0 if eps_now > eps_prev else -1.0)
                    if eg > 0.30: score += 1
                    elif eg > 0.10: score += 0.5
                    elif eps_now < 0: score -= 1.5
                    elif eg < -0.10: score -= 0.5

    # 2. 재무 건전성 (-1 ~ +1)
    if qb is not None and not qb.empty:
        avail = sorted([c for c in qb.columns if c + REPORT_DELAY <= pd.Timestamp(as_of_date)], reverse=True)
        if avail:
            ca = qb.loc["Current Assets", avail[0]] if "Current Assets" in qb.index else None
            cl = qb.loc["Current Liabilities", avail[0]] if "Current Liabilities" in qb.index else None
            if pd.notna(ca) and pd.notna(cl) and cl > 0:
                cr = ca / cl
                if cr > 2: score += 0.5
                elif cr < 0.8: score -= 0.5

    if qc is not None and not qc.empty:
        avail = sorted([c for c in qc.columns if c + REPORT_DELAY <= pd.Timestamp(as_of_date)], reverse=True)
        if avail and "Free Cash Flow" in qc.index:
            fcf = qc.loc["Free Cash Flow", avail[0]]
            if pd.notna(fcf):
                if fcf > 0: score += 0.5
                else: score -= 0.5

    # 3. 내부자 거래 (-1.5 ~ +1.5)
    if insiders is not None and not insiders.empty:
        cutoff = pd.Timestamp(as_of_date) - timedelta(days=90)
        buys = sells = 0
        for _, row in insiders.iterrows():
            txn_date = pd.Timestamp(row.get("Start Date", ""))
            if pd.notna(txn_date) and cutoff <= txn_date <= pd.Timestamp(as_of_date):
                text = str(row.get("Text", "")) + str(row.get("Transaction", ""))
                if "purchase" in text.lower() or "buy" in text.lower():
                    buys += 1
                elif "sale" in text.lower() or "sell" in text.lower():
                    sells += 1
        if buys > sells and buys >= 2: score += 1
        elif buys > 0 and buys > sells: score += 0.5
        elif sells >= 3 and buys == 0: score -= 1
        elif sells > buys and sells >= 2: score -= 0.5

    # 4. 애널리스트 (+1 ~ -1) - 시계열 없으므로 현재값 사용
    if rec is not None and not rec.empty:
        row = rec.iloc[0]
        sb = row.get("strongBuy", 0) or 0
        b = row.get("buy", 0) or 0
        h = row.get("hold", 0) or 0
        s = row.get("sell", 0) or 0
        ss = row.get("strongSell", 0) or 0
        total = sb + b + h + s + ss
        if total > 0:
            w = (1*sb + 2*b + 3*h + 4*s + 5*ss) / total
            if w <= 1.5: score += 1
            elif w <= 2.2: score += 0.5
            elif w >= 3.5: score -= 1

    return max(-5, min(5, round(score, 1)))


def format_detail(d):
    """종목 상세 데이터를 텍스트로 포맷"""
    lines = []
    lines.append(f"  === {d['ticker']} ({d['name']}) ===")
    lines.append(f"    현재가: ${d['price']}" if d['price'] else "    현재가: N/A")
    lines.append(f"    시총: ${d['market_cap_B']}B")

    pe = d.get('pe_fwd')
    lines.append(f"    P/E(FWD): {pe:.1f}" if pe else "    P/E(FWD): N/A")

    si = d.get('short_pct')
    if si:
        pct = si * 100 if si < 1 else si
        flag = " *** 높음!" if pct >= 10 else (" ** 주의" if pct >= 5 else "")
        lines.append(f"    공매도비율: {pct:.1f}%{flag}")
    else:
        lines.append("    공매도비율: N/A")

    inst = d.get('inst_pct')
    lines.append(f"    기관보유율: {inst*100:.1f}%" if inst else "    기관보유율: N/A")

    insider = d.get('insider_pct')
    lines.append(f"    내부자보유율: {insider*100:.1f}%" if insider else "    내부자보유율: N/A")

    h, l = d.get('week52_high'), d.get('week52_low')
    if h and l and d['price']:
        pos = (d['price'] - l) / (h - l) * 100 if h != l else 50
        lines.append(f"    52주 범위: ${l:.2f} ~ ${h:.2f} (현재 위치 {pos:.0f}%)")

    dy = d.get('dividend_yield')
    lines.append(f"    배당수익률: {dy:.2f}%" if dy else "    배당수익률: 없음")

    beta = d.get('beta')
    lines.append(f"    베타: {beta:.2f}" if beta else "    베타: N/A")

    txns = d.get('insider_transactions', [])
    if txns:
        buys = sum(1 for t in txns if t['direction'] == 'BUY')
        sells = sum(1 for t in txns if t['direction'] == 'SELL')
        lines.append(f"    내부자거래(최근): 매수 {buys}건 / 매도 {sells}건")
        for t in txns[:5]:
            emoji = "+" if t['direction'] == 'BUY' else "-"
            lines.append(f"      {t['date']} {emoji} {t['insider']}: {t['shares']:,}주")
    else:
        lines.append("    내부자거래: 데이터 없음")

    return "\n".join(lines)


def format_fundamental_score(ticker, fs):
    """펀더멘탈 점수를 텍스트로 포맷"""
    lines = []
    lines.append(f"  {ticker:10s} 펀더멘탈: {fs['score']:+.1f} ({fs['label']})")
    if fs["details"]:
        lines.append(f"    상세: {' | '.join(fs['details'])}")
    return "\n".join(lines)


def main():
    print("=" * 60)
    print("시장 데이터 + 종목 검증 + 펀더멘탈 점수")
    print("=" * 60)

    # 1. 시장 데이터
    print("\n[1] 시장 지수/원자재/환율/국채")
    print("-" * 50)
    for line in fetch_market_data():
        print(line)

    # 2. 보유 종목 검증
    print("\n[2] 보유 종목 검증 데이터")
    print("-" * 50)
    holdings = get_portfolio_tickers()
    all_details = []
    for ticker in sorted(holdings.keys()):
        try:
            detail = fetch_stock_detail(ticker)
            all_details.append(detail)
            print(format_detail(detail))
            print()
        except Exception as e:
            print(f"  === {ticker}: 조회 실패 ({e}) ===\n")

    # 3. 공매도 요약
    print("\n[3] 공매도 요약 (높은 순)")
    print("-" * 50)
    short_details = [d for d in all_details if d.get('short_pct')]
    short_details.sort(key=lambda x: x.get('short_pct', 0) or 0, reverse=True)
    for d in short_details:
        si = (d['short_pct'] * 100) if d['short_pct'] and d['short_pct'] < 1 else (d['short_pct'] or 0)
        flag = "!!! 숏스퀴즈 후보" if si >= 15 else ("!! 주의" if si >= 5 else "")
        txns = d.get('insider_transactions', [])
        buys = sum(1 for t in txns if t['direction'] == 'BUY')
        sells = sum(1 for t in txns if t['direction'] == 'SELL')
        insider_signal = f"매수{buys}/매도{sells}"
        print(f"  {d['ticker']:8s} | 공매도 {si:5.1f}% | 기관 {(d.get('inst_pct',0) or 0)*100:5.1f}% | 내부자 {insider_signal:10s} | {flag}")

    # 4. 펀더멘탈 점수
    print("\n[4] 펀더멘탈 점수")
    print("-" * 50)
    fund_scores = {}
    for ticker in sorted(holdings.keys()):
        try:
            fs = calc_fundamental_score(ticker)
            fund_scores[ticker] = fs
            print(format_fundamental_score(ticker, fs))
        except Exception as e:
            print(f"  {ticker}: 점수 계산 실패 ({e})")

    # 점수 요약
    if fund_scores:
        print(f"\n  {'─' * 50}")
        sorted_fs = sorted(fund_scores.items(), key=lambda x: x[1]["score"], reverse=True)
        for ticker, fs in sorted_fs:
            bar_pos = "█" * int(max(0, fs["score"]))
            bar_neg = "█" * int(abs(min(0, fs["score"])))
            if fs["score"] >= 0:
                print(f"  {ticker:10s} {fs['score']:+5.1f} {fs['label']:8s} |{'':>5s}{bar_pos}")
            else:
                print(f"  {ticker:10s} {fs['score']:+5.1f} {fs['label']:8s} |{bar_neg:>5s}")

    # 4v2. 펀더멘탈 점수 v2
    print("\n[4] 펀더멘탈 점수 v2 (8 컴포넌트)")
    print("-" * 50)
    fund_scores_v2 = {}
    for ticker in sorted(holdings.keys()):
        try:
            fs2 = calc_fundamental_score_v2(ticker)
            fund_scores_v2[ticker] = fs2
            print(f"  {ticker:10s} {fs2['score']:+.1f} ({fs2['label']})")
            for d in fs2["details"]:
                print(f"    {d}")
        except Exception as e:
            print(f"  {ticker}: v2 계산 실패 ({e})")
            fund_scores_v2[ticker] = {"score": fund_scores.get(ticker, {}).get("score", 0)}
        print()

    # 5. 검증 기준 안내
    print("\n[5] 숨은진주 발굴 시 반드시 확인할 것")
    print("-" * 50)
    print("  - 공매도 20%+ & 실적 서프라이즈 → 숏스퀴즈 후보 (명시 필요)")
    print("  - 내부자 '매수' 건수 확인 → 매도만 있으면 '내부자 매수' 주장 금지")
    print("  - 기관보유율 변화 → yfinance는 최신 13F 기준이므로 45일 지연")
    print("  - 52주 위치 → 신저가 근처 + 기관 매집 = 강한 시그널")
    print("  - P/E(FWD) 음수 = 적자 전망 → 리스크 명시 필요")

    # 6. Finnhub 뉴스 센티먼트 v2
    print("\n[6] 뉴스 센티먼트 v2 (7일 윈도우)")
    print("-" * 50)
    news_scores = {}
    try:
        from news_sentiment import (init_finnhub_client, fetch_current_sentiment,
                                    calc_news_score_v2, calc_analyst_component)
        client = init_finnhub_client()
        sentiment = fetch_current_sentiment(client, sorted(holdings.keys()))

        for ticker in sorted(holdings.keys()):
            data = sentiment.get(ticker, {})
            ns = data.get("news_score", {})
            # 애널리스트 컴포넌트 추가
            analyst = calc_analyst_component(ticker)
            kw_score = ns.get("score", 0)
            combined = max(-5, min(5, round(kw_score + analyst["score"], 1)))
            news_scores[ticker] = combined

            if not ns or ns.get("article_count", 0) == 0:
                # 뉴스 없어도 애널리스트 점수는 있을 수 있음
                if analyst["score"] != 0:
                    ib = " ⚠️IB관계" if analyst["ib_warning"] else ""
                    print(f"  {ticker:10s} 뉴스: {combined:+.1f} (기사0건, 애널리스트: {analyst['score']:+.1f}{ib})")
                continue

            scandal = " *** 스캔들!" if ns.get("scandal_detected") else ""
            ib = " ⚠️IB관계" if analyst["ib_warning"] else ""
            print(f"  {ticker:10s} 뉴스: {combined:+.1f} "
                  f"(기사{ns['article_count']}건, "
                  f"부정{ns['negative_count']}/긍정{ns['positive_count']}){scandal}")
            print(f"    키워드 기반: {kw_score:+.1f} (소스 가중 적용)")
            print(f"    애널리스트: {analyst['score']:+.1f} ({analyst['details']}){ib}")
            # 소스 분포
            src_counts = ns.get("source_counts", {})
            if src_counts:
                top_src = sorted(src_counts.items(), key=lambda x: x[1], reverse=True)[:5]
                src_str = ", ".join(f"{s} {c}" for s, c in top_src)
                print(f"    소스 분포: {src_str}")
            if ns.get("scandal_keywords"):
                print(f"    스캔들: {', '.join(ns['scandal_keywords'])}")
            if ns.get("top_negative"):
                print(f"    최악: {ns['top_negative'][:80]}")

        mkt = sentiment.get("_market", {}).get("sentiment", {})
        if mkt:
            print(f"\n  매크로 센티먼트: {mkt.get('score', 0):+.1f} "
                  f"(기사{mkt.get('article_count', 0)}건)")
    except Exception as e:
        print(f"  Finnhub 조회 실패: {e}")

    # 7. 수급 점수
    print("\n[7] 수급 점수")
    print("-" * 50)
    sd_scores = {}
    for ticker in sorted(holdings.keys()):
        try:
            sd = calc_supply_demand_score(ticker)
            sd_scores[ticker] = sd
            print(f"  {ticker:10s} {sd['score']:+.1f} ({sd['label']})")
            for d in sd["details"]:
                print(f"    {d}")
            print(f"    → 판정: {sd['verdict']}")
        except Exception as e:
            print(f"  {ticker}: 수급 점수 실패 ({e})")
            sd_scores[ticker] = {"score": 0, "verdict": "N/A"}
        print()

    # 8. 종합 점수
    print("\n[8] 종합 점수 (Technical + Fundamental + Supply/Demand + Sentiment)")
    print("-" * 70)
    print(f"  {'종목':10s} {'기술':>6s} {'펀더':>6s} {'수급':>6s} {'센티':>6s} {'종합':>6s}  판정")
    print(f"  {'─' * 65}")

    # 기술적 점수는 technical_analysis.py에서 가져와야 하므로 여기서는 N/A 표시
    # 실제 보고서에서는 technical_analysis.py 실행 결과와 합산
    tech_available = False
    try:
        tech_output = os.path.join(BASE_DIR, ".tech_scores.json")
        if os.path.exists(tech_output):
            with open(tech_output, "r") as f:
                tech_scores_data = json.load(f)
            tech_available = True
    except Exception:
        tech_scores_data = {}

    for ticker in sorted(holdings.keys()):
        fund_s = fund_scores_v2.get(ticker, {}).get("score", 0)
        sd_s = sd_scores.get(ticker, {}).get("score", 0)
        sent_s = news_scores.get(ticker, 0)

        if tech_available and ticker in tech_scores_data:
            tech_s = tech_scores_data[ticker]
        else:
            tech_s = 0  # 기술적 점수 미사용 시 0

        comp = calc_comprehensive_score(tech_s, fund_s, sd_s, sent_s)

        # 수급 verdict 추가
        sd_verdict = sd_scores.get(ticker, {}).get("verdict", "")
        special_mark = ""
        if "셰이크아웃" in sd_verdict:
            special_mark = " 셰이크아웃"
        elif "분배" in sd_verdict:
            special_mark = " ⚠️분배"
        elif "숏스퀴즈" in sd_verdict:
            special_mark = " 숏스퀴즈"

        tech_str = f"{tech_s:+.1f}" if tech_available else "N/A"
        print(f"  {ticker:10s} {tech_str:>6s} {fund_s:+5.1f} {sd_s:+5.1f} {sent_s:+5.1f} {comp['score']:+5.1f}  {comp['label']}{special_mark}")

    if not tech_available:
        print(f"\n  ※ 기술적 점수는 technical_analysis.py 실행 후 .tech_scores.json에서 로드됩니다.")
        print(f"    보고서 생성 시 run_report.sh가 순서대로 실행하여 자동 합산됩니다.")


if __name__ == "__main__":
    main()
