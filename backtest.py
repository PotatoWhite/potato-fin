#!/usr/bin/env python3
"""100일 백테스트 시뮬레이션 (기술적 + 펀더멘탈 + 뉴스 + 수급 통합)

technical_analysis.py + market_data.py + news_sentiment.py의 신호를 과거 100일에 적용.

버전:
- v3: 기술적 점수만
- v5: 기술적 + 과거 펀더멘탈
- v6: 기술적 + 과거 펀더멘탈 + 뉴스 센티먼트
- v7: 기술적 + 과거 펀더멘탈 + 뉴스 + 수급 (내부자/공매도)
"""

import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

# technical_analysis.py + market_data.py 임포트
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from technical_analysis import (
    get_portfolio_tickers,
    calc_atr,
    calc_moving_averages,
    calc_rsi,
    calc_macd,
    calc_bollinger,
    calc_fibonacci,
    calc_volume_profile,
    calc_volume_analysis,
    calc_pivot_points,
    calc_trend_strength,
    calc_stop_target,
    calc_composite_score,
)
from market_data import calc_fundamental_score, prefetch_historical_data, calc_historical_fund_score_fast, calc_supply_demand_score
from news_sentiment import init_finnhub_client, prefetch_news_data, calc_historical_news_score_fast, NON_US_SUFFIXES, NEWS_WINDOW_DAYS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOOKBACK = 200      # 지표 계산에 필요한 사전 데이터 (200MA용)
BACKTEST_DAYS = 100  # 백테스트 기간


def fetch_long_history(tickers):
    """백테스트용 장기 데이터 (1년)"""
    data = {}
    raw = yf.download(tickers, period="1y", progress=False, group_by="ticker")
    for ticker in tickers:
        try:
            if len(tickers) == 1:
                df = raw.copy()
            else:
                df = raw[ticker].copy()
            df = df.dropna(subset=["Close"])
            if not df.empty:
                data[ticker] = df
        except Exception:
            pass
    return data


def analyze_at_date(df_slice):
    """특정 날짜까지의 데이터로 분석 실행 (analyze_ticker와 동일 로직)"""
    price = round(float(df_slice["Close"].iloc[-1]), 2)
    atr = calc_atr(df_slice)
    mas = calc_moving_averages(df_slice)
    rsi = calc_rsi(df_slice)
    macd = calc_macd(df_slice)
    bollinger = calc_bollinger(df_slice)
    fib = calc_fibonacci(df_slice)
    pivot = calc_pivot_points(df_slice)
    trend = calc_trend_strength(df_slice)
    stop_target = calc_stop_target(price, atr, fib, bollinger, mas, pivot)
    composite = calc_composite_score(price, rsi, macd, bollinger, trend, mas)

    return {
        "price": price,
        "atr": round(atr, 2),
        "atr_pct": round(atr / price * 100, 2),
        "rsi": rsi,
        "macd": macd,
        "bollinger": bollinger,
        "mas": mas,
        "trend": trend,
        "stop_target": stop_target,
        "composite": composite,
    }


def run_signal_backtest(ticker, df, bt_start_idx, fund_data=None, news_data=None, sd_score_val=None):
    """종합 신호 점수 기반 매매 시뮬레이션 v7

    v3: 순수 기술적 (fund_data=None, news_data=None)
    v5: 기술적 + 과거 펀더멘탈 (fund_data provided)
    v6: 기술적 + 과거 펀더멘탈 + 뉴스 센티먼트 (fund_data + news_data)
    v7: v6 + 수급 점수 (sd_score_val provided)

    - 진입: tech_score >= 1.0 (순수 기술적, 변경 없음)
    - 퇴출: exit_score = tech_score + fund_adj + news_adj + sd_adj
    - fund_adj = 분기 재무제표 기반 × 0.3 (cap ±0.5)
    - news_adj = 7일 뉴스 센티먼트 × 0.2 (cap ±0.3)
    - sd_adj = 수급 점수 × 0.25 (cap ±0.4) — v7 신규
    """
    cash = 10000.0
    shares = 0
    position = "none"  # none / long
    trades = []
    daily_scores = []
    peak_price = 0
    last_sell_idx = -999  # 마지막 매도 인덱스 (쿨다운용)
    was_golden_at_entry = False  # 진입 시 정배열 여부

    for i in range(bt_start_idx, len(df)):
        df_slice = df.iloc[:i + 1]
        if len(df_slice) < 35:
            continue

        try:
            result = analyze_at_date(df_slice)
        except Exception:
            continue

        date = df.index[i]
        price = result["price"]
        tech_score = result["composite"]["score"]
        label = result["composite"]["label"]
        atr = result["atr"]
        is_golden = result["trend"]["is_golden"]
        is_death = result["trend"]["is_death"]

        # 날짜별 과거 펀더멘탈 점수 (분기마다 변경)
        fund_adj = 0.0
        if fund_data is not None:
            date_str = str(date)[:10]
            # 분기마다 1번만 계산 (캐시)
            if not hasattr(run_signal_backtest, '_fund_cache'):
                run_signal_backtest._fund_cache = {}
            cache_key = (ticker, date_str[:7])  # 월별 캐시
            if cache_key not in run_signal_backtest._fund_cache:
                fs = calc_historical_fund_score_fast(fund_data, date_str)
                run_signal_backtest._fund_cache[cache_key] = fs
            fund_raw = run_signal_backtest._fund_cache[cache_key]
            fund_adj = max(-0.5, min(0.5, fund_raw * 0.3))

        # 뉴스 센티먼트 보정 (v6)
        news_adj = 0.0
        if news_data is not None:
            date_str = str(date)[:10]
            if not hasattr(run_signal_backtest, '_news_cache'):
                run_signal_backtest._news_cache = {}
            news_key = (ticker, date_str)  # 일별 캐시
            if news_key not in run_signal_backtest._news_cache:
                ns = calc_historical_news_score_fast(news_data, date_str)
                run_signal_backtest._news_cache[news_key] = ns
            news_raw = run_signal_backtest._news_cache[news_key]
            news_adj = max(-0.3, min(0.3, news_raw * 0.2))

        # 수급 보정 (v7) — 현재 시점 수급 점수 (과거 시계열 없으므로 고정값 사용)
        sd_adj = 0.0
        if sd_score_val is not None:
            sd_adj = max(-0.4, min(0.4, sd_score_val * 0.25))

        # 퇴출용 점수: 기술적 + 펀더멘탈 + 뉴스 + 수급 보정
        exit_score = max(-5, min(5, round(tech_score + fund_adj + news_adj + sd_adj, 1)))

        daily_scores.append({
            "date": date,
            "price": price,
            "score": tech_score,
            "exit_score": exit_score,
            "fund_adj": fund_adj,
            "news_adj": news_adj,
            "sd_adj": sd_adj,
            "label": label,
            "rsi": result["rsi"],
        })

        if position == "long":
            peak_price = max(peak_price, price)

        # 매수: 순수 기술적 tech_score >= 1.0 + 역배열 아닐 때 + 3일 쿨다운
        cooldown_ok = (i - last_sell_idx) >= 3
        if position == "none" and tech_score >= 1.0 and not is_death and cooldown_ok:
            shares = cash / price
            cash = 0
            position = "long"
            peak_price = price
            was_golden_at_entry = is_golden
            trades.append({"date": date, "action": "BUY", "price": price, "score": tech_score, "reason": f"신호{tech_score:+.1f}"})

        elif position == "long":
            sell_reason = None

            if is_golden or was_golden_at_entry:
                # 정배열: 추세 추종 — 퇴출에 펀더멘탈 보정 적용
                if exit_score <= -2.0:
                    sell_reason = f"신호{exit_score:+.1f}" + (f"(F{fund_adj:+.1f})" if fund_adj else "")
                elif is_death:
                    sell_reason = "역배열전환"
            else:
                # 비정배열: 트레일링 스탑 + 신호 (퇴출에 펀더멘탈 보정)
                trailing_stop = peak_price - 3 * atr
                if exit_score <= -1.5:
                    sell_reason = f"신호{exit_score:+.1f}" + (f"(F{fund_adj:+.1f})" if fund_adj else "")
                elif price <= trailing_stop:
                    sell_reason = f"트레일링(고점{peak_price:.2f}-ATR×3)"
                elif is_death and exit_score <= 0:
                    sell_reason = "역배열전환"

            if sell_reason:
                cash = shares * price
                shares = 0
                position = "none"
                peak_price = 0
                last_sell_idx = i
                was_golden_at_entry = False
                trades.append({"date": date, "action": "SELL", "price": price, "score": exit_score, "reason": sell_reason})

    # 마지막 날 정산
    final_price = float(df["Close"].iloc[-1])
    if position == "long":
        portfolio_value = shares * final_price
    else:
        portfolio_value = cash

    # 바이앤홀드
    start_price = float(df["Close"].iloc[bt_start_idx])
    buyhold_value = 10000.0 * (final_price / start_price)

    return {
        "signal_return": round((portfolio_value / 10000 - 1) * 100, 2),
        "buyhold_return": round((buyhold_value / 10000 - 1) * 100, 2),
        "trades": trades,
        "daily_scores": daily_scores,
        "final_value": round(portfolio_value, 2),
        "buyhold_value": round(buyhold_value, 2),
    }


def run_support_resistance_test(ticker, df, bt_start_idx):
    """지지선/저항선 적중률 테스트"""
    support_tests = []
    resistance_tests = []
    stop_hit = 0
    target_hit = 0
    total_stop_target = 0

    for i in range(bt_start_idx, len(df) - 1):
        df_slice = df.iloc[:i + 1]
        if len(df_slice) < 35:
            continue

        try:
            result = analyze_at_date(df_slice)
        except Exception:
            continue

        # 다음 날 데이터
        next_day = df.iloc[i + 1]
        next_low = float(next_day["Low"])
        next_high = float(next_day["High"])
        next_close = float(next_day["Close"])
        price = result["price"]

        st = result["stop_target"]

        # 지지선 테스트: 다음날 저가가 지지선 근처(±0.5%)에서 반등했는지
        for name, level in st["supports"][:3]:
            if level <= 0:
                continue
            tolerance = level * 0.005
            # 지지선 근처까지 하락했는지
            if next_low <= level + tolerance:
                # 반등했는지 (종가가 지지선 위)
                bounced = next_close > level
                support_tests.append({
                    "level_name": name,
                    "level": level,
                    "next_low": next_low,
                    "next_close": next_close,
                    "bounced": bounced,
                })

        # 저항선 테스트: 다음날 고가가 저항선 근처에서 막혔는지
        for name, level in st["resistances"][:3]:
            if level <= 0:
                continue
            tolerance = level * 0.005
            if next_high >= level - tolerance:
                rejected = next_close < level
                resistance_tests.append({
                    "level_name": name,
                    "level": level,
                    "next_high": next_high,
                    "next_close": next_close,
                    "rejected": rejected,
                })

        # 향후 5일 내 추천 손절/목표 도달 여부 확인
        if i + 5 < len(df):
            future_5d = df.iloc[i + 1:i + 6]
            future_low = float(future_5d["Low"].min())
            future_high = float(future_5d["High"].max())

            total_stop_target += 1
            if future_low <= st["recommended_stop"]:
                stop_hit += 1
            if future_high >= st["recommended_target"]:
                target_hit += 1

    support_bounced = sum(1 for s in support_tests if s["bounced"])
    resistance_rejected = sum(1 for r in resistance_tests if r["rejected"])

    return {
        "support_total": len(support_tests),
        "support_bounced": support_bounced,
        "support_rate": round(support_bounced / len(support_tests) * 100, 1) if support_tests else 0,
        "resistance_total": len(resistance_tests),
        "resistance_rejected": resistance_rejected,
        "resistance_rate": round(resistance_rejected / len(resistance_tests) * 100, 1) if resistance_tests else 0,
        "stop_target_days": total_stop_target,
        "stop_hit_5d": stop_hit,
        "stop_hit_rate": round(stop_hit / total_stop_target * 100, 1) if total_stop_target else 0,
        "target_hit_5d": target_hit,
        "target_hit_rate": round(target_hit / total_stop_target * 100, 1) if total_stop_target else 0,
    }


def run_rsi_macd_test(ticker, df, bt_start_idx):
    """RSI/MACD 신호 정확도 테스트"""
    rsi_signals = []
    macd_signals = []

    for i in range(bt_start_idx, len(df) - 5):
        df_slice = df.iloc[:i + 1]
        if len(df_slice) < 35:
            continue

        try:
            result = analyze_at_date(df_slice)
        except Exception:
            continue

        price = result["price"]
        # 5일 후 가격
        future_price = float(df["Close"].iloc[min(i + 5, len(df) - 1)])
        future_return = (future_price - price) / price * 100

        # RSI 신호
        rsi = result["rsi"]
        if rsi <= 30:
            rsi_signals.append({"type": "과매도", "rsi": rsi, "return_5d": round(future_return, 2)})
        elif rsi >= 70:
            rsi_signals.append({"type": "과매수", "rsi": rsi, "return_5d": round(future_return, 2)})

        # MACD 크로스
        macd = result["macd"]
        if macd and macd["cross"]:
            macd_signals.append({"type": macd["cross"], "return_5d": round(future_return, 2)})

    # RSI 정확도
    oversold = [s for s in rsi_signals if s["type"] == "과매도"]
    overbought = [s for s in rsi_signals if s["type"] == "과매수"]
    oversold_correct = sum(1 for s in oversold if s["return_5d"] > 0)
    overbought_correct = sum(1 for s in overbought if s["return_5d"] < 0)

    # MACD 정확도
    golden = [s for s in macd_signals if s["type"] == "골든크로스"]
    death = [s for s in macd_signals if s["type"] == "데드크로스"]
    golden_correct = sum(1 for s in golden if s["return_5d"] > 0)
    death_correct = sum(1 for s in death if s["return_5d"] < 0)

    return {
        "rsi_oversold_count": len(oversold),
        "rsi_oversold_correct": oversold_correct,
        "rsi_oversold_avg_return": round(np.mean([s["return_5d"] for s in oversold]), 2) if oversold else 0,
        "rsi_overbought_count": len(overbought),
        "rsi_overbought_correct": overbought_correct,
        "rsi_overbought_avg_return": round(np.mean([s["return_5d"] for s in overbought]), 2) if overbought else 0,
        "macd_golden_count": len(golden),
        "macd_golden_correct": golden_correct,
        "macd_golden_avg_return": round(np.mean([s["return_5d"] for s in golden]), 2) if golden else 0,
        "macd_death_count": len(death),
        "macd_death_correct": death_correct,
        "macd_death_avg_return": round(np.mean([s["return_5d"] for s in death]), 2) if death else 0,
    }


def main():
    print("=" * 70)
    print(f"기술적 분석 백테스트 v3/v5/v6/v7 (최근 {BACKTEST_DAYS}일)")
    print("=" * 70)

    holdings = get_portfolio_tickers()
    tickers = sorted(holdings.keys())
    print(f"\n{len(tickers)}개 종목 데이터 다운로드 중 (1년치)...")

    history = fetch_long_history(tickers)

    # 과거 재무제표 + 현재 펀더멘탈 점수 조회
    print(f"\n펀더멘탈 데이터 조회 중...")
    fund_scores = {}  # 현재 시점 점수 (참고)
    hist_fund_data = {}  # 과거 재무제표 (백테스트용)
    for ticker in tickers:
        try:
            fs = calc_fundamental_score(ticker)
            fund_scores[ticker] = fs
        except Exception:
            fund_scores[ticker] = {"score": 0, "label": "N/A", "details": [], "raw": {}}
        try:
            hist_fund_data[ticker] = prefetch_historical_data(ticker)
        except Exception:
            hist_fund_data[ticker] = None
        print(f"    {ticker:10s} 현재: {fund_scores[ticker]['score']:+.1f}({fund_scores[ticker]['label']})")

    # Finnhub 뉴스 프리페치 (v6)
    print(f"\nFinnhub 뉴스 프리페치 중 (디스크 캐시 활용)...")
    hist_news_data = {}
    try:
        finnhub_client = init_finnhub_client()
        for ticker in tickers:
            if any(ticker.endswith(s) for s in NON_US_SUFFIXES):
                hist_news_data[ticker] = None
                print(f"    {ticker:10s} 뉴스: 비미국 (건너뜀)")
                continue
            try:
                # 백테스트 범위: bt_start - 7일 ~ 오늘
                if ticker in history:
                    df = history[ticker]
                    bt_idx = len(df) - BACKTEST_DAYS
                    bt_start = df.index[bt_idx]
                    start_d = (bt_start - pd.Timedelta(days=NEWS_WINDOW_DAYS)).strftime("%Y-%m-%d")
                    end_d = df.index[-1].strftime("%Y-%m-%d")
                    news = prefetch_news_data(finnhub_client, ticker, start_d, end_d)
                    hist_news_data[ticker] = news
                    print(f"    {ticker:10s} 뉴스: {len(news)}건")
                else:
                    hist_news_data[ticker] = None
            except Exception as e:
                hist_news_data[ticker] = None
                print(f"    {ticker:10s} 뉴스: 실패 ({e})")
    except Exception as e:
        print(f"  Finnhub 초기화 실패: {e} (v6 건너뜀)")

    # 수급 점수 조회 (v7) — 현재 시점 고정값 사용 (과거 시계열 없음)
    print(f"\n수급 점수 조회 중 (현재 시점 스냅샷)...")
    sd_scores = {}
    for ticker in tickers:
        try:
            sd = calc_supply_demand_score(ticker)
            sd_scores[ticker] = sd["score"]
            print(f"    {ticker:10s} 수급: {sd['score']:+.1f} ({sd['verdict']})")
        except Exception:
            sd_scores[ticker] = 0
            print(f"    {ticker:10s} 수급: 0 (조회 실패)")

    all_signal_v3 = []  # v3: 순수 기술적
    all_signal_v5 = []  # v5: 과거 펀더멘탈 통합
    all_signal_v6 = []  # v6: 기술적 + 펀더멘탈 + 뉴스
    all_signal_v7 = []  # v7: v6 + 수급
    all_sr = []
    all_rsi_macd = []

    for ticker in tickers:
        if ticker not in history:
            print(f"\n  {ticker}: 데이터 없음 - 건너뜀")
            continue

        df = history[ticker]
        if len(df) < BACKTEST_DAYS + 50:
            print(f"\n  {ticker}: 데이터 부족 ({len(df)}일) - 건너뜀")
            continue

        bt_start_idx = len(df) - BACKTEST_DAYS
        name = holdings[ticker]["name"]
        fs = fund_scores.get(ticker, {"score": 0, "label": "N/A"})

        print(f"\n  {'─' * 65}")
        print(f"  {ticker} ({name}) | 데이터: {len(df)}일 | 현재 펀더멘탈: {fs['score']:+.1f}")
        print(f"  {'─' * 65}")

        # 캐시 초기화 (종목별)
        if hasattr(run_signal_backtest, '_fund_cache'):
            run_signal_backtest._fund_cache = {}

        # 1a. v3: 순수 기술적 (fund_data=None)
        sig_v3 = run_signal_backtest(ticker, df, bt_start_idx, fund_data=None)
        all_signal_v3.append({"ticker": ticker, "name": name, **sig_v3})

        # 캐시 초기화
        if hasattr(run_signal_backtest, '_fund_cache'):
            run_signal_backtest._fund_cache = {}

        # 1b. v5: 과거 펀더멘탈 통합
        fd = hist_fund_data.get(ticker)
        sig_v5 = run_signal_backtest(ticker, df, bt_start_idx, fund_data=fd)
        all_signal_v5.append({"ticker": ticker, "name": name, **sig_v5})

        # 캐시 초기화
        for attr in ('_fund_cache', '_news_cache'):
            if hasattr(run_signal_backtest, attr):
                setattr(run_signal_backtest, attr, {})

        # 1c. v6: 과거 펀더멘탈 + 뉴스 센티먼트
        nd = hist_news_data.get(ticker)
        sig_v6 = run_signal_backtest(ticker, df, bt_start_idx, fund_data=fd, news_data=nd)
        all_signal_v6.append({"ticker": ticker, "name": name, **sig_v6})

        # 캐시 초기화
        for attr in ('_fund_cache', '_news_cache'):
            if hasattr(run_signal_backtest, attr):
                setattr(run_signal_backtest, attr, {})

        # 1d. v7: v6 + 수급 점수
        sd_val = sd_scores.get(ticker, 0)
        sig_v7 = run_signal_backtest(ticker, df, bt_start_idx, fund_data=fd, news_data=nd, sd_score_val=sd_val)
        all_signal_v7.append({"ticker": ticker, "name": name, **sig_v7})

        diff_v3 = sig_v3["signal_return"] - sig_v3["buyhold_return"]
        diff_v5 = sig_v5["signal_return"] - sig_v5["buyhold_return"]
        diff_v6 = sig_v6["signal_return"] - sig_v6["buyhold_return"]
        diff_v7 = sig_v7["signal_return"] - sig_v7["buyhold_return"]

        imp_v7 = sig_v7["signal_return"] - sig_v6["signal_return"]
        print(f"    [v3 기술적만] {sig_v3['signal_return']:+.2f}% | B&H: {sig_v3['buyhold_return']:+.2f}% | {diff_v3:+.2f}%p | 거래 {len(sig_v3['trades'])}건")
        print(f"    [v5 과거펀더] {sig_v5['signal_return']:+.2f}% | B&H: {sig_v5['buyhold_return']:+.2f}% | {diff_v5:+.2f}%p | 거래 {len(sig_v5['trades'])}건")
        print(f"    [v6 +뉴스  ] {sig_v6['signal_return']:+.2f}% | B&H: {sig_v6['buyhold_return']:+.2f}% | {diff_v6:+.2f}%p | 거래 {len(sig_v6['trades'])}건")
        print(f"    [v7 +수급  ] {sig_v7['signal_return']:+.2f}% | B&H: {sig_v7['buyhold_return']:+.2f}% | {diff_v7:+.2f}%p | 거래 {len(sig_v7['trades'])}건")
        if imp_v7 != 0:
            arrow = "▲" if imp_v7 > 0 else "▼"
            print(f"    → v7 vs v6: {arrow} {imp_v7:+.2f}%p")

        if sig_v7["trades"]:
            for t in sig_v7["trades"][:6]:
                print(f"      → {t['action']} {t['price']:,.2f} ({t.get('reason','')})")

        # 2. 지지/저항 적중률
        sr = run_support_resistance_test(ticker, df, bt_start_idx)
        all_sr.append({"ticker": ticker, "name": name, **sr})

        print(f"    [지지/저항] 지지 반등: {sr['support_bounced']}/{sr['support_total']}({sr['support_rate']}%) | 저항 저지: {sr['resistance_rejected']}/{sr['resistance_total']}({sr['resistance_rate']}%)")
        print(f"      5일내 손절 도달: {sr['stop_hit_5d']}/{sr['stop_target_days']}({sr['stop_hit_rate']}%) | 목표 도달: {sr['target_hit_5d']}/{sr['stop_target_days']}({sr['target_hit_rate']}%)")

        # 3. RSI/MACD 신호 정확도
        rm = run_rsi_macd_test(ticker, df, bt_start_idx)
        all_rsi_macd.append({"ticker": ticker, "name": name, **rm})

        if rm["rsi_oversold_count"] > 0:
            rate = rm["rsi_oversold_correct"] / rm["rsi_oversold_count"] * 100
            print(f"    [RSI 과매도] {rm['rsi_oversold_correct']}/{rm['rsi_oversold_count']}({rate:.0f}%) 정확 | 5일 평균 수익 {rm['rsi_oversold_avg_return']:+.2f}%")
        if rm["rsi_overbought_count"] > 0:
            rate = rm["rsi_overbought_correct"] / rm["rsi_overbought_count"] * 100
            print(f"    [RSI 과매수] {rm['rsi_overbought_correct']}/{rm['rsi_overbought_count']}({rate:.0f}%) 정확 | 5일 평균 수익 {rm['rsi_overbought_avg_return']:+.2f}%")
        if rm["macd_golden_count"] > 0:
            rate = rm["macd_golden_correct"] / rm["macd_golden_count"] * 100
            print(f"    [MACD 골든] {rm['macd_golden_correct']}/{rm['macd_golden_count']}({rate:.0f}%) 정확 | 5일 평균 수익 {rm['macd_golden_avg_return']:+.2f}%")
        if rm["macd_death_count"] > 0:
            rate = rm["macd_death_correct"] / rm["macd_death_count"] * 100
            print(f"    [MACD 데드] {rm['macd_death_correct']}/{rm['macd_death_count']}({rate:.0f}%) 정확 | 5일 평균 수익 {rm['macd_death_avg_return']:+.2f}%")

    # === 종합 요약 ===
    print(f"\n{'=' * 70}")
    print("종합 요약: v3 (기술) vs v5 (+펀더) vs v6 (+뉴스) vs v7 (+수급)")
    print("=" * 70)

    print(f"\n[1] 신호 매매: v3 vs v5 vs v6 vs v7 vs B&H")
    print(f"  {'종목':10s} {'v3':>9s} {'v5':>9s} {'v6':>9s} {'v7':>9s} {'B&H':>9s} {'v7vsB&H':>9s} {'v7vs6':>8s}")
    print(f"  {'─' * 80}")

    total_v3 = total_v5 = total_v6 = total_v7 = total_bh = 0
    win_v3 = win_v5 = win_v6 = win_v7 = improved_v7 = 0

    for s3, s5, s6, s7 in zip(all_signal_v3, all_signal_v5, all_signal_v6, all_signal_v7):
        diff_v7 = s7["signal_return"] - s7["buyhold_return"]
        imp7 = s7["signal_return"] - s6["signal_return"]
        arrow = "▲" if imp7 > 0 else ("▼" if imp7 < 0 else "─")

        print(f"  {s3['ticker']:10s} {s3['signal_return']:+8.2f}% {s5['signal_return']:+8.2f}% {s6['signal_return']:+8.2f}% {s7['signal_return']:+8.2f}% {s3['buyhold_return']:+8.2f}% {diff_v7:+8.2f}%p {arrow}{imp7:+6.2f}%p")

        total_v3 += s3["signal_return"]
        total_v5 += s5["signal_return"]
        total_v6 += s6["signal_return"]
        total_v7 += s7["signal_return"]
        total_bh += s3["buyhold_return"]
        d3 = s3["signal_return"] - s3["buyhold_return"]
        d5 = s5["signal_return"] - s5["buyhold_return"]
        d6 = s6["signal_return"] - s6["buyhold_return"]
        d7 = s7["signal_return"] - s7["buyhold_return"]
        if d3 > 0: win_v3 += 1
        if d5 > 0: win_v5 += 1
        if d6 > 0: win_v6 += 1
        if d7 > 0: win_v7 += 1
        if imp7 > 0.01: improved_v7 += 1

    n = len(all_signal_v3)
    if n > 0:
        avg_v3 = total_v3 / n
        avg_v5 = total_v5 / n
        avg_v6 = total_v6 / n
        avg_v7 = total_v7 / n
        avg_bh = total_bh / n
        print(f"  {'─' * 80}")
        print(f"  {'평균':10s} {avg_v3:+8.2f}% {avg_v5:+8.2f}% {avg_v6:+8.2f}% {avg_v7:+8.2f}% {avg_bh:+8.2f}% {avg_v7-avg_bh:+8.2f}%p {avg_v7-avg_v6:+6.2f}%p")
        print(f"  B&H 대비   {avg_v3-avg_bh:+8.2f}%p {avg_v5-avg_bh:+8.2f}%p {avg_v6-avg_bh:+8.2f}%p {avg_v7-avg_bh:+8.2f}%p")
        print(f"  승률       {win_v3}/{n}{'':>5s} {win_v5}/{n}{'':>5s} {win_v6}/{n}{'':>5s} {win_v7}/{n}{'':>5s} {'':>9s} {improved_v7}/{n}개선")

    # 지지/저항 적중률 종합
    print(f"\n[2] 지지선/저항선 적중률 종합")
    total_sup = sum(s["support_total"] for s in all_sr)
    total_sup_ok = sum(s["support_bounced"] for s in all_sr)
    total_res = sum(s["resistance_total"] for s in all_sr)
    total_res_ok = sum(s["resistance_rejected"] for s in all_sr)
    total_st = sum(s["stop_target_days"] for s in all_sr)
    total_stop_hit = sum(s["stop_hit_5d"] for s in all_sr)
    total_tgt_hit = sum(s["target_hit_5d"] for s in all_sr)

    sup_rate = total_sup_ok / total_sup * 100 if total_sup else 0
    res_rate = total_res_ok / total_res * 100 if total_res else 0
    stop_rate = total_stop_hit / total_st * 100 if total_st else 0
    tgt_rate = total_tgt_hit / total_st * 100 if total_st else 0

    print(f"  지지선 반등: {total_sup_ok}/{total_sup} ({sup_rate:.1f}%)")
    print(f"  저항선 저지: {total_res_ok}/{total_res} ({res_rate:.1f}%)")
    print(f"  5일내 손절 도달: {total_stop_hit}/{total_st} ({stop_rate:.1f}%) ← 낮을수록 좋음")
    print(f"  5일내 목표 도달: {total_tgt_hit}/{total_st} ({tgt_rate:.1f}%) ← 높을수록 좋음")

    # RSI/MACD 정확도 종합
    print(f"\n[3] RSI/MACD 신호 정확도 종합")
    rsi_os = sum(s["rsi_oversold_count"] for s in all_rsi_macd)
    rsi_os_ok = sum(s["rsi_oversold_correct"] for s in all_rsi_macd)
    rsi_ob = sum(s["rsi_overbought_count"] for s in all_rsi_macd)
    rsi_ob_ok = sum(s["rsi_overbought_correct"] for s in all_rsi_macd)
    macd_gc = sum(s["macd_golden_count"] for s in all_rsi_macd)
    macd_gc_ok = sum(s["macd_golden_correct"] for s in all_rsi_macd)
    macd_dc = sum(s["macd_death_count"] for s in all_rsi_macd)
    macd_dc_ok = sum(s["macd_death_correct"] for s in all_rsi_macd)

    print(f"  RSI 과매도(<=30) → 5일 후 상승: {rsi_os_ok}/{rsi_os} ({rsi_os_ok/rsi_os*100:.1f}%)" if rsi_os else "  RSI 과매도: 신호 없음")
    print(f"  RSI 과매수(>=70) → 5일 후 하락: {rsi_ob_ok}/{rsi_ob} ({rsi_ob_ok/rsi_ob*100:.1f}%)" if rsi_ob else "  RSI 과매수: 신호 없음")
    print(f"  MACD 골든크로스 → 5일 후 상승: {macd_gc_ok}/{macd_gc} ({macd_gc_ok/macd_gc*100:.1f}%)" if macd_gc else "  MACD 골든크로스: 신호 없음")
    print(f"  MACD 데드크로스 → 5일 후 하락: {macd_dc_ok}/{macd_dc} ({macd_dc_ok/macd_dc*100:.1f}%)" if macd_dc else "  MACD 데드크로스: 신호 없음")

    # 결론
    print(f"\n{'=' * 70}")
    print("결론")
    print(f"{'=' * 70}")

    if n > 0:
        avg_diff_v3 = (total_v3 - total_bh) / n
        avg_diff_v5 = (total_v5 - total_bh) / n
        avg_diff_v6 = (total_v6 - total_bh) / n
        avg_diff_v7 = (total_v7 - total_bh) / n
        v5_imp = (total_v5 - total_v3) / n
        v6_imp = (total_v6 - total_v5) / n
        v7_imp = (total_v7 - total_v6) / n

        print(f"\n  [v3 기술적만] B&H 대비 평균 {avg_diff_v3:+.2f}%p")
        print(f"  [v5 과거펀더] B&H 대비 평균 {avg_diff_v5:+.2f}%p (v3 대비 {v5_imp:+.2f}%p)")
        print(f"  [v6 +뉴스  ] B&H 대비 평균 {avg_diff_v6:+.2f}%p (v5 대비 {v6_imp:+.2f}%p)")
        print(f"  [v7 +수급  ] B&H 대비 평균 {avg_diff_v7:+.2f}%p (v6 대비 {v7_imp:+.2f}%p)")
        print(f"  v7 개선 종목: {improved_v7}/{n}개")

    if sup_rate >= 60:
        print(f"\n  지지선 반등률 {sup_rate:.1f}% → 신뢰도 높음")
    elif sup_rate >= 45:
        print(f"\n  지지선 반등률 {sup_rate:.1f}% → 참고용")
    else:
        print(f"\n  지지선 반등률 {sup_rate:.1f}% → 개선 필요")

    if stop_rate <= 15:
        print(f"  손절 도달률 {stop_rate:.1f}% → 적정")
    elif stop_rate <= 30:
        print(f"  손절 도달률 {stop_rate:.1f}% → 약간 타이트")
    else:
        print(f"  손절 도달률 {stop_rate:.1f}% → 너무 타이트!")


if __name__ == "__main__":
    main()
