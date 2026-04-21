#!/usr/bin/env python3
"""기술적 분석 데이터 생성

보고서 생성 전 실행하여 데이터 기반 매매 타점을 제공한다.
- ATR 기반 손절선/목표가
- 이동평균선 (20/50/100/200MA)
- MACD (12/26/9)
- 피보나치 되돌림/확장
- 볼린저 밴드
- RSI
- 거래량 프로파일 (가격대별 거래량 밀집)
- 피벗 포인트 (Classic)
- 종합 신호 점수 (-5 ~ +5)
- alert_config.json 자동 갱신 (--update-alerts)
"""

import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ALERT_CONFIG = os.path.join(BASE_DIR, "alert_config.json")


def get_portfolio_tickers():
    """SQLite에서 보유 종목 티커 추출"""
    from portfolio_db import get_tickers
    return get_tickers()


def fetch_history(tickers, period="6mo"):
    """종목별 일봉 데이터 다운로드 — 네이버 우선, yfinance fallback.

    Phase C 2026-04-21: naver_finance.get_ohlcv() 사용.
    - 한국 종목: 네이버 chart API (외국인 보유율 컬럼 ForeignPct 포함)
    - 해외 종목: 네이버 basic (현재가) + yfinance fallback (full OHLCV)
    - BAYN.DE 등 미지원: yfinance
    """
    import naver_finance

    # period → days 변환 (1mo=30, 3mo=90, 6mo=180, 1y=365)
    days_map = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730}
    days = days_map.get(period, 180)

    data = {}
    # 한국 종목은 네이버로 개별 조회 (외국인 보유율 포함)
    for ticker in tickers:
        try:
            if ticker.endswith((".KS", ".KQ")):
                df = naver_finance.get_ohlcv(ticker, days=days)
                if df is not None and not df.empty:
                    data[ticker] = df
                    continue
        except Exception:
            pass

    # 해외 종목은 yfinance batch download (더 효율적)
    remaining = [t for t in tickers if t not in data]
    if remaining:
        try:
            raw = yf.download(remaining, period=period, progress=False, group_by="ticker")
            for ticker in remaining:
                try:
                    if len(remaining) == 1:
                        df = raw.copy()
                    else:
                        df = raw[ticker].copy()
                    df = df.dropna(subset=["Close"])
                    if not df.empty:
                        data[ticker] = df
                except Exception:
                    pass
        except Exception:
            pass

    return data


def calc_atr(df, period=14):
    """ATR (Average True Range) 계산"""
    high = df["High"]
    low = df["Low"]
    close = df["Close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - close).abs(),
        (low - close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]


def calc_moving_averages(df):
    """이동평균선 계산"""
    close = df["Close"]
    result = {}
    for p in [20, 50, 100, 200]:
        if len(close) >= p:
            result[f"MA{p}"] = round(float(close.rolling(p).mean().iloc[-1]), 2)
    return result


def calc_rsi(df, period=14):
    """RSI 계산"""
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 1)


def calc_macd(df, fast=12, slow=26, signal=9):
    """MACD 계산"""
    close = df["Close"]
    if len(close) < slow + signal:
        return None
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    # 크로스 감지: 최근 5일 내 크로스 발생 여부
    cross = None
    for i in range(-5, 0):
        if i - 1 < -len(histogram):
            continue
        prev_hist = float(histogram.iloc[i - 1])
        curr_hist = float(histogram.iloc[i])
        if prev_hist <= 0 < curr_hist:
            cross = "골든크로스"
        elif prev_hist >= 0 > curr_hist:
            cross = "데드크로스"

    return {
        "macd": round(float(macd_line.iloc[-1]), 4),
        "signal": round(float(signal_line.iloc[-1]), 4),
        "histogram": round(float(histogram.iloc[-1]), 4),
        "cross": cross,
        "rising": float(histogram.iloc[-1]) > float(histogram.iloc[-2]),
    }


def calc_bollinger(df, period=20, std_mult=2):
    """볼린저 밴드 계산"""
    close = df["Close"]
    if len(close) < period:
        return None
    ma = close.rolling(period).mean()
    std = close.rolling(period).std()
    return {
        "upper": round(float((ma + std_mult * std).iloc[-1]), 2),
        "middle": round(float(ma.iloc[-1]), 2),
        "lower": round(float((ma - std_mult * std).iloc[-1]), 2),
    }


def calc_fibonacci(df):
    """최근 스윙 고점/저점 기반 피보나치 되돌림 + 확장"""
    close = df["Close"]
    high_val = float(close.max())
    low_val = float(close.min())
    diff = high_val - low_val

    high_idx = close.idxmax()
    low_idx = close.idxmin()
    is_uptrend = high_idx > low_idx

    levels = {}
    if is_uptrend:
        levels["swing_high"] = round(high_val, 2)
        levels["swing_low"] = round(low_val, 2)
        levels["fib_236"] = round(high_val - diff * 0.236, 2)
        levels["fib_382"] = round(high_val - diff * 0.382, 2)
        levels["fib_500"] = round(high_val - diff * 0.500, 2)
        levels["fib_618"] = round(high_val - diff * 0.618, 2)
        levels["fib_ext_1272"] = round(low_val + diff * 1.272, 2)
        levels["fib_ext_1618"] = round(low_val + diff * 1.618, 2)
    else:
        levels["swing_high"] = round(high_val, 2)
        levels["swing_low"] = round(low_val, 2)
        levels["fib_236"] = round(low_val + diff * 0.236, 2)
        levels["fib_382"] = round(low_val + diff * 0.382, 2)
        levels["fib_500"] = round(low_val + diff * 0.500, 2)
        levels["fib_618"] = round(low_val + diff * 0.618, 2)
        levels["fib_ext_1272"] = round(high_val - diff * 1.272, 2)
        levels["fib_ext_1618"] = round(high_val - diff * 1.618, 2)

    levels["trend"] = "상승" if is_uptrend else "하락"
    return levels


def calc_volume_profile(df, bins=20):
    """거래량 프로파일: 가격대별 거래량 밀집도"""
    close = df["Close"].values
    volume = df["Volume"].values

    if len(close) == 0 or np.nansum(volume) == 0:
        return []

    price_min, price_max = float(np.nanmin(close)), float(np.nanmax(close))
    if price_min == price_max:
        return []

    edges = np.linspace(price_min, price_max, bins + 1)
    profile = []
    total_vol = float(np.nansum(volume))

    for i in range(bins):
        mask = (close >= edges[i]) & (close < edges[i + 1])
        vol = float(np.nansum(volume[mask]))
        profile.append({
            "price_low": round(edges[i], 2),
            "price_high": round(edges[i + 1], 2),
            "price_mid": round((edges[i] + edges[i + 1]) / 2, 2),
            "volume": int(vol),
            "pct": round(vol / total_vol * 100, 1) if total_vol > 0 else 0,
        })

    profile.sort(key=lambda x: x["volume"], reverse=True)
    return profile


def calc_volume_analysis(df, period=20):
    """거래량 분석: 평균 대비 비율, 급증/급감, 추세 확인

    Returns:
        dict: {
            current_vol: 당일 거래량,
            avg_vol_20: 20일 평균 거래량,
            vol_ratio: 당일/평균 비율,
            vol_signal: "급증"/"증가"/"보통"/"감소"/"급감",
            vol_trend: 5일 거래량 추세 ("증가"/"감소"/"횡보"),
            price_vol_confirm: 가격-거래량 확인 여부,
            score: 거래량 신호 점수 (-1 ~ +1),
            details: str
        }
    """
    if len(df) < period + 5:
        return None

    vol = df["Volume"].values
    close = df["Close"].values

    current_vol = float(vol[-1])
    avg_vol = float(np.nanmean(vol[-period - 1:-1]))  # 당일 제외 20일 평균

    if avg_vol == 0 or np.isnan(avg_vol):
        return None

    vol_ratio = round(current_vol / avg_vol, 2)

    # 거래량 신호
    if vol_ratio >= 3.0:
        vol_signal = "폭증"
    elif vol_ratio >= 2.0:
        vol_signal = "급증"
    elif vol_ratio >= 1.3:
        vol_signal = "증가"
    elif vol_ratio >= 0.7:
        vol_signal = "보통"
    elif vol_ratio >= 0.4:
        vol_signal = "감소"
    else:
        vol_signal = "급감"

    # 5일 거래량 추세 (이동평균 기울기)
    vol_5d_avg = float(np.nanmean(vol[-5:]))
    vol_prev_5d_avg = float(np.nanmean(vol[-10:-5]))
    if vol_prev_5d_avg > 0:
        vol_trend_ratio = vol_5d_avg / vol_prev_5d_avg
        if vol_trend_ratio >= 1.2:
            vol_trend = "증가"
        elif vol_trend_ratio <= 0.8:
            vol_trend = "감소"
        else:
            vol_trend = "횡보"
    else:
        vol_trend = "횡보"

    # 가격-거래량 확인 (Price-Volume Confirmation)
    # 상승 + 거래량 증가 = 확인 (강세)
    # 하락 + 거래량 증가 = 확인 (약세, 셀오프)
    # 상승 + 거래량 감소 = 미확인 (의심스러운 상승)
    # 하락 + 거래량 감소 = 미확인 (관심 부족)
    price_change = float(close[-1]) - float(close[-2])
    vol_change = current_vol > avg_vol

    if price_change > 0 and vol_change:
        pv_confirm = "상승+거래량증가(강세확인)"
        pv_score = 0.5
    elif price_change < 0 and vol_change:
        pv_confirm = "하락+거래량증가(셀오프)"
        pv_score = -0.5
    elif price_change > 0 and not vol_change:
        pv_confirm = "상승+거래량감소(미확인)"
        pv_score = -0.25
    elif price_change < 0 and not vol_change:
        pv_confirm = "하락+거래량감소(관심부족)"
        pv_score = 0.25  # 약한 긍정 (하락 동력 약함)
    else:
        pv_confirm = "보합"
        pv_score = 0

    # 종합 거래량 점수
    vol_score = pv_score
    if vol_ratio >= 2.0 and price_change > 0:
        vol_score += 0.5  # 거래량 폭증 + 상승 = 돌파 확인
    elif vol_ratio >= 2.0 and price_change < 0:
        vol_score -= 0.5  # 거래량 폭증 + 하락 = 패닉셀
    vol_score = max(-1.0, min(1.0, round(vol_score, 2)))

    return {
        "current_vol": int(current_vol),
        "avg_vol_20": int(avg_vol),
        "vol_ratio": vol_ratio,
        "vol_signal": vol_signal,
        "vol_trend": vol_trend,
        "price_vol_confirm": pv_confirm,
        "score": vol_score,
        "details": f"거래량 {vol_ratio:.1f}x({vol_signal}), 추세 {vol_trend}, {pv_confirm}",
    }


def calc_pivot_points(df):
    """클래식 피벗 포인트 (전일 기준)"""
    if len(df) < 2:
        return None
    prev = df.iloc[-2]
    h = float(prev["High"])
    l = float(prev["Low"])
    c = float(prev["Close"])
    pivot = (h + l + c) / 3
    return {
        "R3": round(h + 2 * (pivot - l), 2),
        "R2": round(pivot + (h - l), 2),
        "R1": round(2 * pivot - l, 2),
        "P": round(pivot, 2),
        "S1": round(2 * pivot - h, 2),
        "S2": round(pivot - (h - l), 2),
        "S3": round(l - 2 * (h - pivot), 2),
    }


def calc_trend_strength(df):
    """추세 강도 판단 (이평선 배열 + 가격 위치)"""
    close = float(df["Close"].iloc[-1])
    mas = calc_moving_averages(df)

    above_count = sum(1 for v in mas.values() if close > v)
    total = len(mas)

    ma_values = [mas.get(f"MA{p}") for p in [20, 50, 100, 200] if f"MA{p}" in mas]
    if len(ma_values) >= 3:
        is_golden = all(ma_values[i] >= ma_values[i + 1] for i in range(len(ma_values) - 1))
        is_death = all(ma_values[i] <= ma_values[i + 1] for i in range(len(ma_values) - 1))
    else:
        is_golden = False
        is_death = False

    if is_golden:
        arrangement = "정배열 (강세)"
    elif is_death:
        arrangement = "역배열 (약세)"
    else:
        arrangement = "혼조"

    return {
        "above_ma_count": f"{above_count}/{total}",
        "above_count": above_count,
        "total": total,
        "arrangement": arrangement,
        "is_golden": is_golden,
        "is_death": is_death,
    }


def calc_composite_score(price, rsi, macd, bollinger, trend, mas, volume_analysis=None):
    """종합 신호 점수 (-5 강한매도 ~ +5 강한매수)

    v2 튜닝: 추세 컨텍스트 반영
    - 정배열(상승추세)에서 과매수 패널티 제거 (추세를 따라감)
    - 역배열(하락추세)에서 과매도 보너스 축소 (낙하하는 칼 방지)
    - 가격의 MA 대비 위치 점수 추가
    - MACD는 히스토그램 방향 위주 (크로스는 확인용)
    """
    score = 0
    details = []
    is_uptrend = trend["is_golden"]
    is_downtrend = trend["is_death"]

    # 1. RSI (-2 ~ +2) - 추세 컨텍스트 반영
    if is_uptrend:
        # 상승추세: 과매도는 강한 매수 기회, 과매수는 무시 (추세 추종)
        if rsi <= 20:
            score += 2; details.append("RSI 극과매도+상승추세(+2)")
        elif rsi <= 30:
            score += 1.5; details.append("RSI 과매도+상승추세(+1.5)")
        elif rsi >= 80:
            pass  # 상승추세에서 과매수는 무시
        elif rsi >= 70:
            pass  # 상승추세에서 과매수는 무시
    elif is_downtrend:
        # 하락추세: 과매도 보너스 축소 (낙하하는 칼), 과매수는 강한 매도
        if rsi <= 20:
            score += 0.5; details.append("RSI 극과매도+하락추세(+0.5)")
        elif rsi <= 30:
            pass  # 하락추세에서 과매도는 함정일 수 있음
        elif rsi >= 80:
            score -= 2; details.append("RSI 극과매수+하락추세(-2)")
        elif rsi >= 70:
            score -= 1.5; details.append("RSI 과매수+하락추세(-1.5)")
    else:
        # 혼조: 기본 로직
        if rsi <= 20:
            score += 2; details.append("RSI 극과매도(+2)")
        elif rsi <= 30:
            score += 1; details.append("RSI 과매도(+1)")
        elif rsi >= 80:
            score -= 1.5; details.append("RSI 극과매수(-1.5)")
        elif rsi >= 70:
            score -= 1; details.append("RSI 과매수(-1)")

    # 2. MACD (-1 ~ +1) - 히스토그램 방향 위주
    if macd:
        if macd["histogram"] > 0 and macd["rising"]:
            score += 0.5; details.append("MACD▲ 양(+0.5)")
        elif macd["histogram"] > 0 and not macd["rising"]:
            score += 0.25; details.append("MACD 양↘(+0.25)")
        elif macd["histogram"] < 0 and macd["rising"]:
            score -= 0.25; details.append("MACD 음↗(-0.25)")
        elif macd["histogram"] < 0 and not macd["rising"]:
            score -= 0.5; details.append("MACD▼ 음(-0.5)")

        # 크로스는 확인 보너스 (+0.5 only)
        if macd["cross"] == "골든크로스":
            score += 0.5; details.append("MACD 골든크로스(+0.5)")
        elif macd["cross"] == "데드크로스":
            score -= 0.5; details.append("MACD 데드크로스(-0.5)")

    # 3. 볼린저 위치 (-1 ~ +1) - 추세 컨텍스트 반영
    if bollinger:
        bb_range = bollinger["upper"] - bollinger["lower"]
        if bb_range > 0:
            bb_pos = (price - bollinger["lower"]) / bb_range
            if bb_pos <= 0.05:
                score += 1; details.append("BB 하단 이탈(+1)")
            elif bb_pos <= 0.2:
                score += 0.5; details.append("BB 하단 근접(+0.5)")
            elif bb_pos >= 0.95:
                if is_uptrend:
                    pass  # 상승추세에서 BB 상단 이탈은 모멘텀
                else:
                    score -= 1; details.append("BB 상단 이탈(-1)")
            elif bb_pos >= 0.8:
                if not is_uptrend:
                    score -= 0.5; details.append("BB 상단 근접(-0.5)")

    # 4. 이평선 배열 (-1 ~ +1)
    if is_uptrend:
        score += 1; details.append("이평선 정배열(+1)")
    elif is_downtrend:
        score -= 1; details.append("이평선 역배열(-1)")

    # 5. 거래량 분석 (-1 ~ +1)
    if volume_analysis:
        vs = volume_analysis["score"]
        if vs != 0:
            score += vs
            details.append(f"거래량 {volume_analysis['vol_ratio']:.1f}x({vs:+.2f})")

    # 6. 가격의 MA 대비 위치 (-1 ~ +1)
    above = trend["above_count"]
    total = trend["total"]
    if total > 0:
        ratio = above / total
        if ratio >= 0.75:
            score += 1; details.append(f"MA 위 {above}/{total}(+1)")
        elif ratio >= 0.5:
            score += 0.5; details.append(f"MA 위 {above}/{total}(+0.5)")
        elif ratio <= 0.25 and total >= 3:
            score -= 1; details.append(f"MA 위 {above}/{total}(-1)")
        elif ratio < 0.5:
            score -= 0.5; details.append(f"MA 위 {above}/{total}(-0.5)")

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


def calc_stop_target(price, atr, fib, bollinger, mas, pivot):
    """ATR + 기술적 레벨 종합하여 손절/목표 산출"""
    atr_stop = round(price - 2 * atr, 2)
    atr_target = round(price + 3 * atr, 2)

    supports = []
    if atr_stop < price:
        supports.append(("ATR×2", atr_stop))
    for key in ["fib_382", "fib_500", "fib_618"]:
        if key in fib and fib[key] < price:
            label = key.replace("fib_", "Fib ").replace("_", ".")
            supports.append((label, fib[key]))
    if bollinger and bollinger["lower"] < price:
        supports.append(("BB하단", bollinger["lower"]))
    for ma_key in ["MA50", "MA100", "MA200"]:
        if ma_key in mas and mas[ma_key] < price:
            supports.append((ma_key, mas[ma_key]))
    if pivot:
        for key in ["S1", "S2"]:
            if pivot[key] < price:
                supports.append((f"Pivot {key}", pivot[key]))

    resistances = []
    if atr_target > price:
        resistances.append(("ATR×3", atr_target))
    for key in ["fib_236", "fib_382", "fib_500"]:
        if key in fib and fib[key] > price:
            label = key.replace("fib_", "Fib ").replace("_", ".")
            resistances.append((label, fib[key]))
    for key in ["fib_ext_1272", "fib_ext_1618"]:
        if key in fib and fib[key] > price:
            label = key.replace("fib_ext_", "Fib Ext ")
            resistances.append((label, fib[key]))
    if bollinger and bollinger["upper"] > price:
        resistances.append(("BB상단", bollinger["upper"]))
    for ma_key in ["MA20", "MA50", "MA100"]:
        if ma_key in mas and mas[ma_key] > price:
            resistances.append((ma_key, mas[ma_key]))
    if pivot:
        for key in ["R1", "R2"]:
            if pivot[key] > price:
                resistances.append((f"Pivot {key}", pivot[key]))

    supports.sort(key=lambda x: x[1], reverse=True)
    resistances.sort(key=lambda x: x[1])

    recommended_stop = atr_stop
    if supports:
        nearby = [s for s in supports if abs(s[1] - atr_stop) <= atr]
        if nearby:
            recommended_stop = min(s[1] for s in nearby)

    recommended_target = atr_target
    if resistances:
        recommended_target = resistances[0][1]

    return {
        "recommended_stop": round(recommended_stop, 2),
        "recommended_target": round(recommended_target, 2),
        "atr_stop": atr_stop,
        "atr_target": atr_target,
        "supports": supports[:5],
        "resistances": resistances[:5],
    }


def analyze_ticker(ticker, df):
    """단일 종목 기술적 분석 실행"""
    price = round(float(df["Close"].iloc[-1]), 2)
    atr = calc_atr(df)
    mas = calc_moving_averages(df)
    rsi = calc_rsi(df)
    macd = calc_macd(df)
    bollinger = calc_bollinger(df)
    fib = calc_fibonacci(df)
    vol_profile = calc_volume_profile(df)
    vol_analysis = calc_volume_analysis(df)
    pivot = calc_pivot_points(df)
    trend = calc_trend_strength(df)
    stop_target = calc_stop_target(price, atr, fib, bollinger, mas, pivot)
    composite = calc_composite_score(price, rsi, macd, bollinger, trend, mas, vol_analysis)

    return {
        "price": price,
        "atr": round(atr, 2),
        "atr_pct": round(atr / price * 100, 2),
        "mas": mas,
        "rsi": rsi,
        "macd": macd,
        "bollinger": bollinger,
        "fibonacci": fib,
        "volume_profile_top3": vol_profile[:3],
        "volume_analysis": vol_analysis,
        "pivot": pivot,
        "trend": trend,
        "stop_target": stop_target,
        "composite": composite,
    }


def format_result(ticker, name, result):
    """분석 결과를 텍스트로 포맷"""
    r = result
    price = r["price"]
    lines = []

    # 종합 점수 헤더
    comp = r["composite"]
    score_bar = "+" * int(max(0, comp["score"])) + "-" * int(abs(min(0, comp["score"])))
    lines.append(f"  === {ticker} ({name}) === 현재가: {price:,} | 신호: {comp['score']:+.1f} {comp['label']} [{score_bar}]")
    lines.append(f"    ATR(14): {r['atr']:,} ({r['atr_pct']}%)")

    # 추세
    t = r["trend"]
    lines.append(f"    추세: 이평선 {t['arrangement']} | 현재가 > MA {t['above_ma_count']}")

    # RSI
    rsi = r["rsi"]
    if rsi >= 70:
        rsi_label = "과매수"
    elif rsi <= 30:
        rsi_label = "과매도"
    elif rsi >= 60:
        rsi_label = "강세"
    elif rsi <= 40:
        rsi_label = "약세"
    else:
        rsi_label = "중립"
    lines.append(f"    RSI(14): {rsi} ({rsi_label})")

    # MACD
    macd = r["macd"]
    if macd:
        cross_str = f" *** {macd['cross']}" if macd["cross"] else ""
        direction = "▲" if macd["rising"] else "▼"
        lines.append(f"    MACD: {macd['macd']:.4f} | Signal: {macd['signal']:.4f} | Hist: {macd['histogram']:.4f} {direction}{cross_str}")

    # 이동평균선
    ma_str = " / ".join(f"{k} {v:,}" for k, v in r["mas"].items())
    lines.append(f"    이평선: {ma_str}")

    # 볼린저 밴드
    bb = r["bollinger"]
    if bb:
        bb_pos = round((price - bb["lower"]) / (bb["upper"] - bb["lower"]) * 100, 0) if bb["upper"] != bb["lower"] else 50
        lines.append(f"    볼린저: {bb['lower']:,} ~ {bb['middle']:,} ~ {bb['upper']:,} (위치 {bb_pos:.0f}%)")

    # 피보나치
    fib = r["fibonacci"]
    lines.append(f"    피보나치 ({fib['trend']} 추세): 고점 {fib['swing_high']:,} / 저점 {fib['swing_low']:,}")
    fib_levels = []
    for key in ["fib_236", "fib_382", "fib_500", "fib_618"]:
        if key in fib:
            label = key.replace("fib_", "").replace("_", ".")
            fib_levels.append(f"{label}%={fib[key]:,}")
    lines.append(f"      되돌림: {' / '.join(fib_levels)}")
    ext_levels = []
    for key in ["fib_ext_1272", "fib_ext_1618"]:
        if key in fib:
            label = key.replace("fib_ext_", "")
            ext_levels.append(f"{label}%={fib[key]:,}")
    if ext_levels:
        lines.append(f"      확장: {' / '.join(ext_levels)}")

    # 거래량 분석
    va = r.get("volume_analysis")
    if va:
        vol_flag = ""
        if va["vol_ratio"] >= 2.0:
            vol_flag = " *** 급증!"
        elif va["vol_ratio"] <= 0.4:
            vol_flag = " ** 급감"
        lines.append(f"    거래량: {va['current_vol']:,} (20일평균 {va['avg_vol_20']:,}, {va['vol_ratio']:.1f}배){vol_flag}")
        lines.append(f"    거래량 신호: {va['vol_signal']} | 추세 {va['vol_trend']} | {va['price_vol_confirm']}")

    # 거래량 밀집
    vp = r["volume_profile_top3"]
    if vp:
        vp_str = " / ".join(f"{v['price_mid']:,}({v['pct']}%)" for v in vp)
        lines.append(f"    거래량 밀집: {vp_str}")

    # 피벗 포인트
    pv = r["pivot"]
    if pv:
        lines.append(f"    피벗(전일): S2={pv['S2']:,} S1={pv['S1']:,} P={pv['P']:,} R1={pv['R1']:,} R2={pv['R2']:,}")

    # 추천 타점
    st = r["stop_target"]
    lines.append(f"    ─── 추천 타점 ───")
    lines.append(f"    손절선: {st['recommended_stop']:,} (ATR기반: {st['atr_stop']:,})")
    lines.append(f"    목표가: {st['recommended_target']:,} (ATR기반: {st['atr_target']:,})")

    if st["supports"]:
        sup_str = " / ".join(f"{s[0]}={s[1]:,}" for s in st["supports"])
        lines.append(f"    지지선: {sup_str}")

    if st["resistances"]:
        res_str = " / ".join(f"{s[0]}={s[1]:,}" for s in st["resistances"])
        lines.append(f"    저항선: {res_str}")

    # 종합 점수 상세
    if comp["details"]:
        lines.append(f"    신호 상세: {' | '.join(comp['details'])}")

    return "\n".join(lines)


def update_alert_config(all_results):
    """분석 결과로 alert_config.json의 stop_loss/target/swing_pct 갱신"""
    if not os.path.exists(ALERT_CONFIG):
        print("  alert_config.json 없음 - 건너뜀")
        return

    with open(ALERT_CONFIG, "r", encoding="utf-8") as f:
        config = json.load(f)

    alerts = config.get("alerts", {})
    updated = []

    for ticker, result in all_results.items():
        if ticker not in alerts:
            continue

        alert = alerts[ticker]
        st = result["stop_target"]
        atr_pct = result["atr_pct"]

        # ETF는 건너뜀
        if alert.get("stop_loss") is None and alert.get("target") is None:
            continue

        old_stop = alert.get("stop_loss")
        old_target = alert.get("target")

        alert["stop_loss"] = st["recommended_stop"]
        alert["target"] = st["recommended_target"]
        alert["swing_pct"] = round(max(3.0, min(7.0, atr_pct * 1.5)), 1)

        comp = result["composite"]
        alert["note"] = (
            f"신호 {comp['score']:+.1f}({comp['label']}). "
            f"손절: ATR×2 기반 {st['atr_stop']:,}. "
            f"RSI {result['rsi']}. "
            f"{result['trend']['arrangement']}."
        )

        changes = []
        if old_stop != alert["stop_loss"]:
            changes.append(f"손절 {old_stop}→{alert['stop_loss']}")
        if old_target != alert["target"]:
            changes.append(f"목표 {old_target}→{alert['target']}")
        if changes:
            updated.append(f"  {ticker}: {', '.join(changes)}")

    now = datetime.now().strftime("%Y-%m-%d %H:%M KST")
    config["_updated"] = now
    config["_source"] = "technical_analysis.py (자동)"

    with open(ALERT_CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    if updated:
        print("\n[alert_config.json 갱신]")
        for line in updated:
            print(line)
    else:
        print("\n[alert_config.json 변경 없음]")


def main():
    print("=" * 60)
    print("기술적 분석 리포트 (6개월 일봉 기준)")
    print("=" * 60)

    do_update_alerts = "--update-alerts" in sys.argv

    holdings = get_portfolio_tickers()
    tickers = sorted(holdings.keys())
    print(f"\n{len(tickers)}개 종목 분석 중...\n")

    history = fetch_history(tickers, period="6mo")

    all_results = {}
    for ticker in tickers:
        if ticker not in history:
            print(f"  === {ticker}: 데이터 없음 ===\n")
            continue

        df = history[ticker]
        if len(df) < 20:
            print(f"  === {ticker}: 데이터 부족 ({len(df)}일) ===\n")
            continue

        try:
            result = analyze_ticker(ticker, df)
            all_results[ticker] = result
            name = holdings[ticker]["name"]
            print(format_result(ticker, name, result))
            print()
        except Exception as e:
            print(f"  === {ticker}: 분석 실패 ({e}) ===\n")

    # 종합 점수 요약
    if all_results:
        print("=" * 60)
        print("종합 신호 점수 요약")
        print("=" * 60)
        sorted_results = sorted(all_results.items(), key=lambda x: x[1]["composite"]["score"], reverse=True)
        for ticker, r in sorted_results:
            comp = r["composite"]
            name = holdings.get(ticker, {}).get("name", "")
            bar_pos = "█" * int(max(0, comp["score"]))
            bar_neg = "█" * int(abs(min(0, comp["score"])))
            if comp["score"] >= 0:
                print(f"  {ticker:10s} {name:20s} {comp['score']:+5.1f} {comp['label']:8s} |{'':>5s}{bar_pos}")
            else:
                print(f"  {ticker:10s} {name:20s} {comp['score']:+5.1f} {comp['label']:8s} |{bar_neg:>5s}")

    if do_update_alerts:
        update_alert_config(all_results)
    else:
        print("\n(alert_config 갱신하려면 --update-alerts 옵션 추가)")

    # 종합 점수 연동용: 기술적 점수를 .tech_scores.json에 저장
    if all_results:
        import json
        tech_scores = {t: r["composite"]["score"] for t, r in all_results.items()}
        scores_path = os.path.join(BASE_DIR, ".tech_scores.json")
        with open(scores_path, "w") as f:
            json.dump(tech_scores, f)
        print(f"\n  기술적 점수 저장됨: {scores_path}")


if __name__ == "__main__":
    main()
