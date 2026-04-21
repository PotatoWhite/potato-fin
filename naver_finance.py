"""
Naver Finance API 통합 래퍼.

사용자 지시 (2026-04-21): "가급적이면 naver api 부터 사용하도록 해라".

커버리지:
  - 한국 주식 (035420, 000660, 005930, 195940, 429760): 차트 API ⭐ 외국인 보유율 포함
  - 미국 주식 (.O = NASDAQ, 접미사 없음 = NYSE): basic + polling API
  - 일본 주식 (1377.T): basic + polling API
  - 독일 주식 (BAYN.DE): **네이버 미지원** → yfinance fallback

Fallback 원칙:
  naver 실패/미지원 → yfinance 호출. 둘 다 실패 → None 반환.

모듈 인터페이스:
  get_price(ticker) -> float | None
  get_ohlcv(ticker, days=30) -> pandas.DataFrame | None
  get_foreign_retention(ticker, days=30) -> pandas.DataFrame | None  (한국만)
  get_market_status(ticker) -> dict | None (거래소/세션 정보, 해외)

티커 변환 규칙:
  yfinance ticker         naver ticker       시장
  ──────────────────────────────────────────
  005930.KS               005930             코스피
  000660.KS               000660             코스피
  035420.KS               035420             코스피
  195940.KQ               195940             코스닥
  429760.KS               429760             코스피 ETF
  NVDA                    NVDA.O             나스닥
  GOOGL                   GOOGL.O            나스닥
  MSFT                    MSFT.O             나스닥
  TSLA                    TSLA.O             나스닥
  PLTR                    PLTR.O             나스닥
  QCOM                    QCOM.O             나스닥
  UNH                     UNH                NYSE
  WRB                     WRB                NYSE
  XOM                     XOM                NYSE
  CVX                     CVX                NYSE
  SLV                     SLV                NYSE ETF
  BOTZ                    BOTZ.O             나스닥 ETF (또는 NYSE ARCA)
  1377.T                  1377.T             도쿄
  BAYN.DE                 (미지원)           → yfinance
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any, Optional

import requests

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
)
HEADERS = {"User-Agent": UA, "Referer": "https://m.stock.naver.com/"}
TIMEOUT = 10

# yfinance 티커 → 네이버 티커 변환
# (명시되지 않은 미국 NASDAQ 종목은 자동 .O 접미사 추가 시도)
YF_TO_NAVER = {
    "005930.KS": "005930",
    "000660.KS": "000660",
    "035420.KS": "035420",
    "195940.KQ": "195940",
    "429760.KS": "429760",
    "NVDA": "NVDA.O",
    "GOOGL": "GOOGL.O",
    "MSFT": "MSFT.O",
    "TSLA": "TSLA.O",
    "PLTR": "PLTR.O",
    "QCOM": "QCOM.O",
    "BOTZ": "BOTZ.O",
    # NYSE 종목 (접미사 없음)
    "UNH": "UNH",
    "WRB": "WRB",
    "XOM": "XOM",
    "CVX": "CVX",
    "SLV": "SLV",
    # 해외
    "1377.T": "1377.T",
    # 네이버 미지원
    "BAYN.DE": None,  # → yfinance fallback
}

KOREAN_EXCHANGES = (".KS", ".KQ")


def is_korean(ticker: str) -> bool:
    return ticker.endswith(KOREAN_EXCHANGES)


def to_naver(ticker: str) -> Optional[str]:
    """yfinance ticker를 네이버 ticker로 변환. None이면 네이버 미지원."""
    if ticker in YF_TO_NAVER:
        return YF_TO_NAVER[ticker]
    # 명시 안 된 미국 종목은 .O 자동 시도 (NASDAQ 대부분)
    if "." not in ticker and ticker.isalpha():
        return f"{ticker}.O"
    return None


# ──────────────────────────────────────────────────────────────────────
# Naver API 호출
# ──────────────────────────────────────────────────────────────────────

def _get_korean_ohlcv(code: str, start: str, end: str) -> Optional[list[dict[str, Any]]]:
    """
    한국 주식 일봉 + 외국인 보유율.

    Returns list of {localDate, closePrice, openPrice, highPrice, lowPrice,
                     accumulatedTradingVolume, foreignRetentionRate}.
    """
    url = (
        f"https://api.stock.naver.com/chart/domestic/item/{code}/day"
        f"?startDateTime={start}0000&endDateTime={end}2359"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        logger.warning(f"naver chart unexpected shape for {code}: {type(data)}")
        return None
    except Exception as e:
        logger.warning(f"naver chart failed for {code}: {e}")
        return None


def _get_foreign_basic(ticker: str) -> Optional[dict[str, Any]]:
    """해외 주식 기본 정보 (종목명/현재가 기본)."""
    url = f"https://api.stock.naver.com/stock/{ticker}/basic"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("code") == "StockConflict":
            return None
        return data
    except Exception as e:
        logger.warning(f"naver basic failed for {ticker}: {e}")
        return None


def _get_foreign_realtime(ticker: str) -> Optional[dict[str, Any]]:
    """해외 주식 실시간 시세 (7초 폴링)."""
    url = f"https://polling.finance.naver.com/api/realtime/worldstock/stock/{ticker}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        datas = data.get("datas", [])
        if datas and isinstance(datas, list):
            return datas[0]
        return None
    except Exception as e:
        logger.warning(f"naver polling failed for {ticker}: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────
# 공개 인터페이스
# ──────────────────────────────────────────────────────────────────────

def get_price(ticker: str) -> Optional[float]:
    """
    현재가 (최근 거래가) 반환. 한국은 원화, 해외는 현지 통화.

    Naver 우선 → yfinance fallback.
    """
    naver_tk = to_naver(ticker)

    def _safe_float(v) -> Optional[float]:
        """NaN / None / 'NaN' 문자열 방어."""
        if v is None:
            return None
        try:
            f = float(v)
            if math.isnan(f) or math.isinf(f) or f <= 0:
                return None
            return f
        except (ValueError, TypeError):
            return None

    if naver_tk:
        if is_korean(ticker):
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
            rows = _get_korean_ohlcv(naver_tk, start, end)
            if rows:
                p = _safe_float(rows[-1].get("closePrice"))
                if p is not None:
                    return p
        else:
            rt = _get_foreign_realtime(naver_tk)
            if rt:
                p = _safe_float(rt.get("closePrice"))
                if p is not None:
                    return p
            basic = _get_foreign_basic(naver_tk)
            if basic:
                p = _safe_float(basic.get("closePrice"))
                if p is not None:
                    return p

    # Fallback → yfinance
    if yf is None:
        logger.error(f"yfinance 없음, ticker={ticker}")
        return None
    try:
        data = yf.Ticker(ticker).history(period="5d", auto_adjust=False)
        if not data.empty:
            p = _safe_float(data["Close"].iloc[-1])
            if p is not None:
                return p
    except Exception as e:
        logger.warning(f"yfinance fallback failed for {ticker}: {e}")
    return None


def get_ohlcv(ticker: str, days: int = 30):
    """
    일봉 OHLCV DataFrame 반환.
    한국: 차트 API (외국인 보유율 포함).
    해외: polling 현재가 + yfinance history 조합 (네이버에 해외 차트 API 없음).
    """
    if pd is None:
        logger.error("pandas 미설치")
        return None

    naver_tk = to_naver(ticker)
    if is_korean(ticker) and naver_tk:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")  # 버퍼
        rows = _get_korean_ohlcv(naver_tk, start, end)
        if rows:
            df = pd.DataFrame(rows)
            df["Date"] = pd.to_datetime(df["localDate"], format="%Y%m%d")
            df = df.rename(
                columns={
                    "openPrice": "Open",
                    "highPrice": "High",
                    "lowPrice": "Low",
                    "closePrice": "Close",
                    "accumulatedTradingVolume": "Volume",
                    "foreignRetentionRate": "ForeignPct",  # ⭐ 한국 특화
                }
            )
            df = df[["Date", "Open", "High", "Low", "Close", "Volume", "ForeignPct"]]
            df = df.set_index("Date").tail(days)
            return df

    # Fallback → yfinance (해외 주식은 기본 경로)
    if yf is None:
        return None
    try:
        df = yf.Ticker(ticker).history(period=f"{days}d", auto_adjust=False)
        if not df.empty:
            df = df.rename_axis("Date")[["Open", "High", "Low", "Close", "Volume"]]
            return df
    except Exception as e:
        logger.warning(f"yfinance OHLCV fallback failed for {ticker}: {e}")
    return None


def get_foreign_retention(ticker: str, days: int = 30):
    """
    한국 주식만: 일별 외국인 보유율 (%) 시계열.

    반환: DataFrame[Date] → ForeignPct (float)
    외국인 순매수 추세의 직접 프록시 (매일 보유율 변화분 = 순매수/매도).
    """
    if not is_korean(ticker):
        return None
    df = get_ohlcv(ticker, days=days)
    if df is None or "ForeignPct" not in df.columns:
        return None
    return df[["ForeignPct"]].copy()


def get_exchange_rate(pair: str) -> Optional[float]:
    """
    환율 조회 — 네이버 marketindex API.

    Args:
        pair: 'USD', 'JPY', 'EUR', 'CNY' — KRW 대비.

    Returns:
        1 단위 통화당 원화 환율 (예: USD→1472.70, JPY→9.257).
        네이버는 JPY를 100엔 기준으로 제공하므로 /100 보정.
    """
    fx_map = {"USD": "FX_USDKRW", "JPY": "FX_JPYKRW", "EUR": "FX_EURKRW", "CNY": "FX_CNYKRW"}
    fx_code = fx_map.get(pair.upper())
    if not fx_code:
        return None

    url = f"https://api.stock.naver.com/marketindex/exchange/{fx_code}/prices?pageSize=1&page=1"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or not data:
            return None
        close_str = data[0].get("closePrice", "").replace(",", "")
        if not close_str:
            return None
        rate = float(close_str)
        # 네이버는 JPY를 100엔 기준으로 표기 — 1엔당 원으로 변환
        if pair.upper() == "JPY":
            rate /= 100.0
        return round(rate, 4)
    except Exception as e:
        logger.warning(f"naver FX failed for {pair}: {e}")
        return None


def get_exchange_history(pair: str, days: int = 30):
    """환율 시계열 DataFrame (한국 증시 영업일 기준)."""
    if pd is None:
        return None
    fx_map = {"USD": "FX_USDKRW", "JPY": "FX_JPYKRW", "EUR": "FX_EURKRW", "CNY": "FX_CNYKRW"}
    fx_code = fx_map.get(pair.upper())
    if not fx_code:
        return None

    url = f"https://api.stock.naver.com/marketindex/exchange/{fx_code}/prices?pageSize={days}&page=1"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list):
            return None
        df_rows = []
        for row in rows:
            close = float(row.get("closePrice", "0").replace(",", ""))
            if pair.upper() == "JPY":
                close /= 100.0
            df_rows.append({"Date": row.get("localTradedAt"), "Close": round(close, 4)})
        df = pd.DataFrame(df_rows)
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        return df
    except Exception as e:
        logger.warning(f"naver FX history failed for {pair}: {e}")
        return None


def _parse_int_str(text: Any) -> int:
    """'+1,295,451' / '-2,876,209' / '16,705,245' / '6,564원' → int. 실패 시 0."""
    if text is None:
        return 0
    s = str(text).strip()
    # 단위 / 부호 제거 (쉼표, +, 원, 배, %)
    for unit in (",", "+", "원", "배", "%", "백만"):
        s = s.replace(unit, "")
    s = s.strip()
    if not s or s == "-":
        return 0
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def _parse_pct_str(text: Any) -> Optional[float]:
    """'49.17%' / '33.36배' / '6,564원' 같은 단위 붙은 숫자 → float. 실패 시 None."""
    if text is None:
        return None
    s = str(text).strip()
    # 단위 제거
    for unit in ("%", "배", "원", "백만", "조", "억", ","):
        s = s.replace(unit, "")
    s = s.strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def get_kr_investor_flow(ticker: str, days: int = 3) -> Optional[dict[str, Any]]:
    """
    한국 종목 일별 수급 데이터 (네이버 integration API).

    dealTrendInfos: 외국인/기관/개인 일별 순매수 수량 + 외인 보유율.
    최대 3일치 제공 (API 제한).

    Returns:
        {
            "ticker": "005930",
            "trend": [
                {
                    "bizdate": "20260421",
                    "foreigner_net": +1295451,  # 순매수 수량 (주)
                    "organ_net": +1226321,
                    "individual_net": -2499998,
                    "foreign_hold_pct": 49.17,
                    "close": 219000,
                }, ...
            ],
            "summary": {
                "foreign_net_total": -4757868,       # 누적 순매수
                "organ_net_total": +2214900,
                "individual_net_total": -717782,
                "foreign_hold_latest": 49.17,
                "foreign_hold_change": -0.03,         # 시작~최신 % 변화
                "days_covered": 3,
            }
        }
        None: 한국 종목 아니거나 API 실패.
    """
    code = _to_korean_code(ticker)
    if not code:
        return None

    url = f"https://m.stock.naver.com/api/stock/{code}/integration"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning(f"naver integration failed for {code}: {e}")
        return None

    trend_raw = data.get("dealTrendInfos", [])
    if not trend_raw:
        return None

    trend = []
    for day in trend_raw[:days]:
        trend.append(
            {
                "bizdate": day.get("bizdate"),
                "foreigner_net": _parse_int_str(day.get("foreignerPureBuyQuant")),
                "organ_net": _parse_int_str(day.get("organPureBuyQuant")),
                "individual_net": _parse_int_str(day.get("individualPureBuyQuant")),
                "foreign_hold_pct": _parse_pct_str(day.get("foreignerHoldRatio")),
                "close": _parse_int_str(day.get("closePrice")),
            }
        )

    if not trend:
        return None

    f_total = sum(t["foreigner_net"] for t in trend)
    o_total = sum(t["organ_net"] for t in trend)
    i_total = sum(t["individual_net"] for t in trend)
    first_hold = trend[-1]["foreign_hold_pct"]  # 가장 오래된 것
    last_hold = trend[0]["foreign_hold_pct"]
    hold_change = (
        round(last_hold - first_hold, 3)
        if first_hold is not None and last_hold is not None
        else None
    )

    return {
        "ticker": code,
        "trend": trend,
        "summary": {
            "foreign_net_total": f_total,
            "organ_net_total": o_total,
            "individual_net_total": i_total,
            "foreign_hold_latest": last_hold,
            "foreign_hold_change": hold_change,
            "days_covered": len(trend),
        },
    }


def get_kr_fundamentals(ticker: str) -> Optional[dict[str, Any]]:
    """
    한국 종목 펀더멘탈 (네이버 integration API의 totalInfos).

    필드: PER/EPS/PBR/BPS/배당수익률/시총/외인소진율/52주최고최저 등.

    Returns:
        {
            "ticker": "005930",
            "per": 15.2,
            "eps": 14400,
            "pbr": 1.3,
            "bps": 168460,
            "div_yield_pct": 2.5,
            "market_cap_str": "1,280조 3,350억",
            "foreign_rate_pct": 49.14,
            "week52_high": 228500,
            "week52_low": 53500,
            "est_per": 18.5,       # 추정 PER
            "est_eps": 11800,
            "close": 219000,
            "open": 217000,
            "volume": 31185230,
        }
    """
    code = _to_korean_code(ticker)
    if not code:
        return None

    url = f"https://m.stock.naver.com/api/stock/{code}/integration"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning(f"naver integration failed for {code}: {e}")
        return None

    infos = data.get("totalInfos", [])
    if not infos:
        return None

    # code → value 매핑
    kv = {info.get("code"): info.get("value") for info in infos if info.get("code")}

    def _num(key, as_float=False):
        v = kv.get(key)
        if v is None:
            return None
        if as_float:
            return _parse_pct_str(v)
        return _parse_int_str(v) if _parse_int_str(v) else _parse_pct_str(v)

    return {
        "ticker": code,
        "per": _parse_pct_str(kv.get("per")),
        "eps": _parse_int_str(kv.get("eps")) or None,
        "pbr": _parse_pct_str(kv.get("pbr")),
        "bps": _parse_int_str(kv.get("bps")) or None,
        "div_yield_pct": _parse_pct_str(kv.get("dividendYieldRatio")),
        "div_per_share": _parse_int_str(kv.get("dividend")) or None,
        "market_cap_str": kv.get("marketValue"),
        "foreign_rate_pct": _parse_pct_str(kv.get("foreignRate")),
        "week52_high": _parse_int_str(kv.get("highPriceOf52Weeks")) or None,
        "week52_low": _parse_int_str(kv.get("lowPriceOf52Weeks")) or None,
        "est_per": _parse_pct_str(kv.get("cnsPer")),
        "est_eps": _parse_int_str(kv.get("cnsEps")) or None,
        "close": _parse_int_str(kv.get("closePrice")) or None,
        "last_close": _parse_int_str(kv.get("lastClosePrice")) or None,
        "open": _parse_int_str(kv.get("openPrice")) or None,
        "high": _parse_int_str(kv.get("highPrice")) or None,
        "low": _parse_int_str(kv.get("lowPrice")) or None,
        "volume": _parse_int_str(kv.get("accumulatedTradingVolume")) or None,
    }


def get_consensus(ticker: str) -> Optional[dict[str, Any]]:
    """
    애널리스트 컨센서스 (한국 + 미국 + 일본 모두 네이버 API에서 지원).

    Returns:
        {
            "ticker": ...,
            "recomm_mean": 4.26,         # 1 (strong sell) ~ 5 (strong buy)
            "target_mean": 264.95,       # 애널 평균 목표가
            "target_high": 432.78,
            "target_low": 138.00,
            "currency": "USD",
            "updated": "2026-04-16",
        }
    """
    naver_tk = to_naver(ticker)
    if not naver_tk:
        return None

    # 한국은 code 그대로, 해외는 .O/.T 등 접미사
    if is_korean(ticker):
        url = f"https://m.stock.naver.com/api/stock/{naver_tk}/integration"
    else:
        url = f"https://api.stock.naver.com/stock/{naver_tk}/integration"

    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning(f"naver consensus failed for {ticker}: {e}")
        return None

    cons = data.get("consensusInfo") or {}
    if not cons:
        return None

    return {
        "ticker": naver_tk,
        "recomm_mean": _parse_pct_str(cons.get("recommMean")),
        "target_mean": _parse_pct_str(cons.get("priceTargetMean")),
        "target_high": _parse_pct_str(cons.get("priceTargetHigh")),
        "target_low": _parse_pct_str(cons.get("priceTargetLow")),
        "currency": (cons.get("currencyType") or {}).get("code", ""),
        "updated": cons.get("createDate", ""),
    }


def get_kr_ir_schedule(ticker: str) -> Optional[list[dict[str, Any]]]:
    """
    한국 종목 IR 스케줄 (실적발표/주주총회 등). 네이버 integration의 irScheduleInfo.
    해외 종목은 미지원.
    """
    code = _to_korean_code(ticker)
    if not code:
        return None

    try:
        r = requests.get(f"https://m.stock.naver.com/api/stock/{code}/integration",
                        headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning(f"naver IR failed for {code}: {e}")
        return None

    ir = data.get("irScheduleInfo") or {}
    events = ir.get("irScheduleList") or []
    return events if events else None


def _to_korean_code(ticker: str) -> Optional[str]:
    """한국 티커 → 6자리 KRX 코드."""
    if ticker.endswith(KOREAN_EXCHANGES):
        return ticker.split(".")[0]
    if ticker.isdigit() and len(ticker) == 6:
        return ticker
    return None


def get_market_status(ticker: str) -> Optional[dict[str, Any]]:
    """해외 종목의 거래소/세션 정보. 미국/일본만 의미."""
    if is_korean(ticker):
        return {"exchange": "KRX", "session": "KST"}
    naver_tk = to_naver(ticker)
    if not naver_tk:
        return None
    rt = _get_foreign_realtime(naver_tk)
    if rt:
        exch = rt.get("stockExchangeType", {})
        return {
            "exchange": exch.get("name", "?"),
            "nation": exch.get("nationName", "?"),
            "session_start": exch.get("startTime", "?"),
            "session_end": exch.get("endTime", "?"),
            "delay_min": exch.get("delayTime", 0),
        }
    return None


# ──────────────────────────────────────────────────────────────────────
# CLI (self-test)
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    print("=== Naver Finance 래퍼 self-test ===\n")

    test_tickers = ["005930.KS", "035420.KS", "NVDA", "UNH", "1377.T", "BAYN.DE"]
    for tk in test_tickers:
        src = "naver" if to_naver(tk) else "yfinance(fallback)"
        price = get_price(tk)
        status = get_market_status(tk)
        print(f"  {tk:12s} [{src:20s}] price={price}")
        if status:
            print(f"    {status}")
    print()

    print("=== 한국 OHLCV + 외국인 보유율 (035420 NAVER, 최근 10일) ===\n")
    df = get_ohlcv("035420.KS", days=10)
    if df is not None:
        print(df.to_string())
        print()
        print("외국인 보유율 변화:")
        fr = get_foreign_retention("035420.KS", days=10)
        if fr is not None:
            fr["일별변화"] = fr["ForeignPct"].diff().round(3)
            print(fr.to_string())
