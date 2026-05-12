#!/usr/bin/env python3
"""Tier 1 뉴스/가격 감시병 (30분마다 실행)

비용: $0 (Claude API 미사용)
역할:
  1. 보유종목 가격/거래량 이상 감지
  2. Finnhub 뉴스 수집 + 키워드 필터링
  3. 경제지표 발표 감지 (Finnhub Calendar)
  4. 데이터 누적 저장 → Tier 2/3에서 활용
  5. 급변 시 텔레그램 즉시 알림 + event_flash.sh 트리거

Usage:
  python3 news_monitor.py              # 1회 실행
  python3 news_monitor.py --daemon     # 30분 간격 반복
"""

import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import finnhub
import yfinance as yf

# ─── 설정 ───

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data", "monitor")
STATE_FILE = os.path.join(BASE_DIR, "data", ".monitor_state.json")
LOG_DIR = os.path.expanduser("~/logs/stock-monitor")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "monitor.log")),
        logging.StreamHandler(),
    ],
)

# .env 로드
def _load_env():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

_load_env()

FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─── 트리거 임계값 ───

PRICE_CHANGE_THRESHOLD = 3.0   # ±3% 이상 → 긴급 알림
VOLUME_SPIKE_THRESHOLD = 2.5   # 평균의 2.5배 이상 → 거래량 이상
NEWS_SCORE_URGENT = -2.0       # 뉴스 점수 -2 이하 → 부정 뉴스 급증
FLASH_COOLDOWN_MIN = 60        # 같은 종목 이벤트 플래시 최소 간격 (분)

# ─── 시장 시간 (KST) ───

MARKETS = {
    "US": {"open": (23, 30), "close": (6, 0), "crosses_midnight": True},
    "KR": {"open": (9, 0), "close": (15, 30), "crosses_midnight": False},
    "JP": {"open": (9, 0), "close": (15, 0), "crosses_midnight": False},
    "EU": {"open": (17, 0), "close": (1, 30), "crosses_midnight": True},
}

TICKER_MARKET = {
    "035420.KS": "KR", "195940.KQ": "KR", "429760.KS": "KR",
    "005930.KS": "KR", "000660.KS": "KR",
    "1377.T": "JP", "BAYN.DE": "EU",
    "BOTZ": "US", "CVX": "US", "GOOGL": "US", "MSFT": "US",
    "NVDA": "US", "PLTR": "US", "QCOM": "US", "SLV": "US",
    "TSLA": "US", "UNH": "US", "WRB": "US", "XOM": "US",
}

# Finnhub 미지원 (비미국)
NON_US_SUFFIXES = ('.KS', '.KQ', '.T', '.DE', '.L', '.HK')

# 종목별 포트폴리오 비중 (alert_config.json에서 동적으로 읽지만 폴백용)
TICKER_NAMES = {
    "035420.KS": "NAVER", "195940.KQ": "HK이노엔", "429760.KS": "PLUS S&P500",
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스",
    "1377.T": "사카타종묘", "BAYN.DE": "바이엘",
    "BOTZ": "BOTZ", "CVX": "셰브론", "GOOGL": "알파벳", "MSFT": "마이크로소프트",
    "NVDA": "엔비디아", "PLTR": "팔란티어", "QCOM": "퀄컴", "SLV": "은ETF",
    "TSLA": "테슬라", "UNH": "유나이티드헬스", "WRB": "WR버클리", "XOM": "엑슨모빌",
}

# ─── 뉴스 키워드 (임팩트 분류) ───

# 🔴 손실 위험 키워드
LOSS_KEYWORDS = {
    # 심각 (포트폴리오 -3%+)
    "SEC investigation": -3, "SEC charges": -3, "DOJ probe": -3,
    "DOJ investigation": -3, "fraud allegation": -3, "accounting fraud": -3,
    "CEO resign": -3, "CEO fired": -3, "CEO arrested": -3,
    "files for bankruptcy": -3, "bankruptcy filing": -3,
    "trading halt": -3, "circuit breaker": -3,
    # 높음 (종목 -5%+)
    "data breach": -2, "massive recall": -2,
    "emergency rate hike": -2, "earnings miss": -2,
    "guidance cut": -2, "profit warning": -2,
    "FDA rejection": -2, "clinical trial fail": -2,
    "tariff increase": -2, "new sanctions": -2,
    # 보통 (종목 -2~3%)
    "downgrade": -1, "lawsuit": -1, "insider selling": -1,
    "layoff": -1, "antitrust": -1,
}

# 🟢 수익 기회 키워드
GAIN_KEYWORDS = {
    # 강한 기회 (종목 +5%+)
    "FDA approval": 3, "breakthrough designation": 3,
    "record revenue": 2, "record earnings": 2,
    "beat expectation": 2, "beats expectation": 2,
    "raised guidance": 2, "raises guidance": 2,
    # 보통 기회 (종목 +2~3%)
    "stock buyback": 1, "dividend increase": 1,
    "insider buying": 1, "institutional buying": 1,
    "upgrade": 1, "new contract": 1, "acquisition approved": 1,
}

# ─── 업계 이벤트/컨퍼런스 캘린더 ───

# 보유 종목/섹터에 직접 영향을 미치는 주요 이벤트
# 매년/매분기 반복 or 고정 일정
INDUSTRY_EVENTS = [
    # AI/반도체 (NVDA, MSFT, GOOGL, QCOM, BOTZ)
    {"name": "NVIDIA GTC", "month": 3, "tickers": ["NVDA", "BOTZ"], "type": "conference",
     "note": "AI 신제품 발표, GPU 로드맵. NVDA 최대 이벤트"},
    {"name": "Google I/O", "month": 5, "tickers": ["GOOGL"], "type": "conference",
     "note": "AI/검색/클라우드 신기능 발표"},
    {"name": "Microsoft Build", "month": 5, "tickers": ["MSFT"], "type": "conference",
     "note": "Azure/Copilot/AI 개발자 행사"},
    {"name": "Apple WWDC", "month": 6, "tickers": ["QCOM"], "type": "conference",
     "note": "Apple Silicon 로드맵 → QCOM 모뎀 내재화 영향"},
    {"name": "Qualcomm Snapdragon Summit", "month": 10, "tickers": ["QCOM"], "type": "conference",
     "note": "차세대 칩 발표. 자동차/PC/모바일 전략"},
    {"name": "CES", "month": 1, "tickers": ["NVDA", "QCOM", "BOTZ", "TSLA"], "type": "conference",
     "note": "전자제품 신기술 총집합. AI/자율주행/로봇"},
    {"name": "MWC Barcelona", "month": 2, "tickers": ["QCOM"], "type": "conference",
     "note": "모바일/5G/6G. QCOM 핵심 무대"},

    # 에너지 (CVX, XOM, SLV)
    {"name": "CERAWeek", "month": 3, "tickers": ["CVX", "XOM"], "type": "conference",
     "note": "에너지 업계 최대 컨퍼런스. OPEC+ 방향 시그널"},
    {"name": "OPEC+ 회의", "month": 6, "tickers": ["CVX", "XOM"], "type": "policy",
     "note": "감산/증산 결정 → 유가 직접 영향"},

    # 헬스케어 (UNH, BAYN.DE)
    {"name": "JPM Healthcare Conference", "month": 1, "tickers": ["UNH", "BAYN.DE"], "type": "conference",
     "note": "바이오/제약 최대 행사. M&A 발표 집중"},
    {"name": "ASCO Annual Meeting", "month": 5, "tickers": ["BAYN.DE"], "type": "conference",
     "note": "종양학 최대 학회. 신약 임상 결과 발표"},

    # 보험 (WRB)
    {"name": "Verisk Insurance Conference", "month": 4, "tickers": ["WRB"], "type": "conference",
     "note": "보험 업계 프라이싱/기후 리스크"},

    # 자율주행/EV (TSLA)
    {"name": "Tesla AI Day", "month": 8, "tickers": ["TSLA", "BOTZ"], "type": "conference",
     "note": "FSD/Optimus/Dojo 업데이트"},

    # 로보틱스 (BOTZ)
    {"name": "automate / ProMat", "month": 5, "tickers": ["BOTZ"], "type": "conference",
     "note": "산업 자동화/물류 로봇 전시"},
    {"name": "IREX (일본 로봇 전시)", "month": 11, "tickers": ["BOTZ", "1377.T"], "type": "conference",
     "note": "일본 로봇/자동화 전시. Fanuc/Keyence"},

    # 금/은 (SLV)
    {"name": "LBMA Precious Metals Conference", "month": 10, "tickers": ["SLV"], "type": "conference",
     "note": "금/은 시장 전망. 중앙은행 수요 데이터"},

    # 한국 (NAVER, HK이노엔)
    {"name": "NAVER DEVIEW", "month": 2, "tickers": ["035420.KS"], "type": "conference",
     "note": "네이버 개발자 컨퍼런스. AI/검색/커머스 신기술"},
    {"name": "바이오코리아", "month": 5, "tickers": ["195940.KQ"], "type": "conference",
     "note": "한국 바이오 산업 전시. 라이선스 딜 발표"},
    {"name": "삼성전자 반도체 파운드리 포럼", "month": 6, "tickers": ["005930.KS"], "type": "conference",
     "note": "삼성 파운드리 로드맵/수주. HBM/GAA 공정 진척"},
    {"name": "SK하이닉스 HBM 발표", "month": 3, "tickers": ["000660.KS"], "type": "conference",
     "note": "HBM4 양산/NVIDIA 공급 계약. AI 메모리 수요"},

    # 정책/매크로 (전체 영향)
    {"name": "Jackson Hole 심포지엄", "month": 8, "tickers": ["_ALL"], "type": "policy",
     "note": "연준 의장 연설. 금리 방향 핵심 시그널"},
    {"name": "FOMC 회의", "month": 0, "tickers": ["_ALL"], "type": "policy",
     "note": "금리 결정. 연 8회 (1/3/5/6/7/9/11/12월)"},
    {"name": "USMCA 리뷰 데드라인", "month": 7, "day": 1, "tickers": ["_ALL"], "type": "policy",
     "note": "7/1 마감. 결렬 시 북미 관세 복원"},
    {"name": "미중 관세 연장 데드라인", "month": 11, "day": 10, "tickers": ["QCOM"], "type": "policy",
     "note": "11/10 만료. QCOM 중국 매출 직접 영향"},
]

# ─── 실적 발표 추적 (yfinance에서 동적 로드) ───

def get_upcoming_earnings():
    """보유종목 실적 발표일 조회 (yfinance)

    Returns:
        list: [{ticker, name, date, days_until}]
    """
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).date()
    upcoming = []

    # ETF는 실적 없음
    etf_tickers = {"BOTZ", "SLV", "429760.KS"}
    for ticker in TICKER_MARKET:
        if any(ticker.endswith(s) for s in NON_US_SUFFIXES):
            continue
        if ticker in etf_tickers:
            continue
        try:
            t = yf.Ticker(ticker)
            # yfinance의 earnings_dates에서 미래 일정 추출
            cal = t.calendar
            if cal is not None and not cal.empty:
                for col in cal.columns:
                    if 'earnings' in str(col).lower() or 'date' in str(col).lower():
                        try:
                            edate = cal[col].iloc[0]
                            if hasattr(edate, 'date'):
                                edate = edate.date()
                            if isinstance(edate, str):
                                edate = datetime.strptime(edate[:10], "%Y-%m-%d").date()
                            days = (edate - today).days
                            if 0 <= days <= 30:
                                upcoming.append({
                                    "ticker": ticker,
                                    "name": TICKER_NAMES.get(ticker, ticker),
                                    "date": str(edate),
                                    "days_until": days,
                                    "type": "earnings",
                                })
                        except Exception:
                            pass
        except Exception:
            pass

    return sorted(upcoming, key=lambda x: x["days_until"])


# ─── 유틸리티 ───

def is_market_open(market_key):
    """현재 KST 기준 시장 개장 여부"""
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    m = MARKETS.get(market_key)
    if not m:
        return False

    current_min = now.hour * 60 + now.minute
    open_min = m["open"][0] * 60 + m["open"][1]
    close_min = m["close"][0] * 60 + m["close"][1]

    if m["crosses_midnight"]:
        return current_min >= open_min or current_min <= close_min
    else:
        return open_min <= current_min <= close_min


def any_market_open():
    """어느 시장이든 열려 있는지"""
    return any(is_market_open(k) for k in MARKETS)


def get_open_markets():
    """현재 열린 시장 리스트"""
    return [k for k in MARKETS if is_market_open(k)]


def get_active_tickers():
    """현재 개장 시장의 종목만 반환"""
    open_markets = get_open_markets()
    return {t: m for t, m in TICKER_MARKET.items() if m in open_markets}


def send_telegram(message, parse_mode="Markdown"):
    """텔레그램 메시지 전송"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("텔레그램 설정 없음")
        return
    try:
        import urllib.request
        import urllib.parse
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": parse_mode,
        }).encode()
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logging.error(f"텔레그램 전송 실패: {e}")


def _has_hangul(s: str) -> bool:
    return any("가" <= c <= "힣" for c in s)


def translate_headlines(headlines):
    """영어 헤드라인 → 한국어. Haiku 배치 호출 + portfolio.db 캐시.

    Returns: {원문: 한국어} dict. 한국어/빈 헤드라인은 원문 그대로.
    실패 시 원문 fallback.
    """
    if not headlines:
        return {}

    unique = list(dict.fromkeys(h for h in headlines if h))
    result = {h: h for h in unique}
    todo = [h for h in unique if not _has_hangul(h)]
    if not todo:
        return result

    db_path = os.path.join(BASE_DIR, "portfolio.db")
    con = sqlite3.connect(db_path)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS news_translation (
            original TEXT PRIMARY KEY,
            korean   TEXT,
            created  TEXT
        )
        """
    )

    uncached = []
    for h in todo:
        row = con.execute(
            "SELECT korean FROM news_translation WHERE original = ?", (h,)
        ).fetchone()
        if row and row[0]:
            result[h] = row[0]
        else:
            uncached.append(h)

    if not uncached:
        con.close()
        return result

    numbered = "\n".join(f"{i+1}. {h}" for i, h in enumerate(uncached))
    prompt = (
        "다음 영어 주식 뉴스 헤드라인들을 한국어로 자연스럽게 번역하라. "
        "번호 보존, 한 줄당 하나. 번역만 출력 (부연 설명/원문/따옴표 금지). "
        "고유명사/티커는 원문 유지.\n\n"
        f"{numbered}"
    )

    claude = shutil.which("claude") or "/home/bravopotato/.npm-global/bin/claude"
    try:
        r = subprocess.run(
            [claude, "--model", "haiku", "--print",
             "--dangerously-skip-permissions", prompt],
            capture_output=True, text=True, timeout=60,
        )
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out:
            lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
            now = datetime.now().isoformat()
            for h, ln in zip(uncached, lines):
                m = re.match(r"^\s*\d+[.)]\s*(.+)$", ln)
                trans = (m.group(1) if m else ln).strip().strip('"').strip("'")
                if trans:
                    result[h] = trans
                    con.execute(
                        "INSERT OR REPLACE INTO news_translation (original, korean, created) VALUES (?, ?, ?)",
                        (h, trans, now),
                    )
            con.commit()
        else:
            logging.warning(f"headline 번역 응답 비어있음 (rc={r.returncode}): {(r.stderr or '')[:200]}")
    except subprocess.TimeoutExpired:
        logging.warning("headline 번역 timeout — 원문 사용")
    except Exception as e:
        logging.warning(f"headline 번역 실패: {e}")
    finally:
        con.close()

    return result


def trigger_event_flash(trigger_data):
    """이벤트 플래시 트리거 (Haiku 분석)"""
    flash_script = os.path.join(BASE_DIR, "event_flash.sh")
    if not os.path.exists(flash_script):
        logging.info("event_flash.sh 미존재, 스킵")
        return

    # 트리거 데이터를 임시 파일로 전달
    trigger_file = os.path.join(DATA_DIR, ".flash_trigger.json")
    with open(trigger_file, "w", encoding="utf-8") as f:
        json.dump(trigger_data, f, ensure_ascii=False, indent=2)

    try:
        subprocess.Popen(
            ["bash", flash_script, trigger_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logging.info(f"이벤트 플래시 트리거: {trigger_data.get('type', 'unknown')}")
    except Exception as e:
        logging.error(f"이벤트 플래시 실행 실패: {e}")


# ─── 상태 관리 ───

def load_state():
    """감시 상태 로드"""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_run": None, "flash_cooldowns": {}, "daily_alerts": {}}


def save_state(state):
    """감시 상태 저장"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def can_flash(ticker, state):
    """이벤트 플래시 쿨다운 확인"""
    cooldowns = state.get("flash_cooldowns", {})
    last = cooldowns.get(ticker)
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        return (datetime.now() - last_dt).total_seconds() > FLASH_COOLDOWN_MIN * 60
    except (ValueError, TypeError):
        return True


def record_flash(ticker, state):
    """이벤트 플래시 쿨다운 기록"""
    if "flash_cooldowns" not in state:
        state["flash_cooldowns"] = {}
    state["flash_cooldowns"][ticker] = datetime.now().isoformat()


# ─── 데이터 수집 ───

def collect_prices(tickers):
    """보유종목 현재가/거래량 수집 + 이상 감지

    Returns:
        dict: {ticker: {price, change_pct, volume, avg_volume, vol_ratio, alerts: []}}
    """
    if not tickers:
        return {}

    ticker_list = list(tickers.keys())
    results = {}

    try:
        data = yf.download(ticker_list, period="5d", progress=False, group_by="ticker")
    except Exception as e:
        logging.error(f"가격 조회 실패: {e}")
        return {}

    import pandas as pd

    for ticker in ticker_list:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                df = data[ticker].copy()
            else:
                df = data.copy()

            # Price 레벨이 있으면 제거
            if isinstance(df.columns, pd.MultiIndex):
                df = df.droplevel(0, axis=1)

            df = df.dropna(subset=["Close"])
            if df.empty or len(df) < 2:
                continue

            current_price = float(df["Close"].iloc[-1])
            prev_close = float(df["Close"].iloc[-2])
            current_vol = float(df["Volume"].iloc[-1])
            avg_vol = float(df["Volume"].iloc[:-1].mean()) if len(df) > 1 else current_vol

            change_pct = ((current_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
            vol_ratio = (current_vol / avg_vol) if avg_vol > 0 else 1.0

            alerts = []
            if abs(change_pct) >= PRICE_CHANGE_THRESHOLD:
                alerts.append(f"{'급등' if change_pct > 0 else '급락'} {change_pct:+.1f}%")
            if vol_ratio >= VOLUME_SPIKE_THRESHOLD:
                alerts.append(f"거래량 {vol_ratio:.1f}x")

            results[ticker] = {
                "price": round(current_price, 2),
                "prev_close": round(prev_close, 2),
                "change_pct": round(change_pct, 2),
                "volume": int(current_vol),
                "avg_volume": int(avg_vol),
                "vol_ratio": round(vol_ratio, 2),
                "alerts": alerts,
            }
        except Exception as e:
            logging.warning(f"{ticker} 가격 처리 실패: {e}")

    return results


def collect_news(tickers):
    """Finnhub 뉴스 수집 + 키워드 분석

    Returns:
        dict: {ticker: {articles: [], urgent: [], positive: [], score: float}}
    """
    if not FINNHUB_KEY:
        logging.warning("FINNHUB_API_KEY 미설정")
        return {}

    client = finnhub.Client(api_key=FINNHUB_KEY)
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    results = {}

    for ticker in tickers:
        if any(ticker.endswith(s) for s in NON_US_SUFFIXES):
            continue

        try:
            time.sleep(1.2)  # Rate limit: 60/min
            articles = client.company_news(ticker, _from=yesterday, to=today)
            if not articles:
                articles = []
        except Exception as e:
            logging.warning(f"{ticker} 뉴스 조회 실패: {e}")
            articles = []

        urgent = []
        positive = []
        score = 0.0

        for article in articles:
            text = (article.get("headline", "") + " " + article.get("summary", "")).lower()

            for kw, weight in LOSS_KEYWORDS.items():
                if kw.lower() in text:
                    urgent.append({
                        "keyword": kw,
                        "headline": article.get("headline", ""),
                        "source": article.get("source", ""),
                        "url": article.get("url", ""),
                        "datetime": article.get("datetime", 0),
                    })
                    score += weight  # weight is negative
                    break

            for kw, weight in GAIN_KEYWORDS.items():
                if kw.lower() in text:
                    positive.append({
                        "keyword": kw,
                        "headline": article.get("headline", ""),
                        "source": article.get("source", ""),
                        "url": article.get("url", ""),
                        "datetime": article.get("datetime", 0),
                    })
                    score += weight  # weight is positive
                    break

        results[ticker] = {
            "article_count": len(articles),
            "urgent": urgent[:5],
            "positive": positive[:5],
            "score": round(max(-5, min(5, score)), 1),
            "top_headlines": [
                {"headline": a.get("headline", ""), "source": a.get("source", ""), "url": a.get("url", "")}
                for a in articles[:5]
            ],
        }

    # 일반 시장 뉴스
    try:
        time.sleep(1.2)
        gen_news = client.general_news('general', min_id=0)
        market_urgent = []
        for article in (gen_news or []):
            text = (article.get("headline", "") + " " + article.get("summary", "")).lower()
            for kw in LOSS_KEYWORDS:
                if kw.lower() in text:
                    market_urgent.append({
                        "keyword": kw,
                        "headline": article.get("headline", ""),
                        "source": article.get("source", ""),
                        "url": article.get("url", ""),
                    })
                    break
        results["_market"] = {
            "article_count": len(gen_news or []),
            "urgent": market_urgent[:5],
            "top_headlines": [
                {"headline": a.get("headline", ""), "source": a.get("source", ""), "url": a.get("url", "")}
                for a in (gen_news or [])[:5]
            ],
        }
    except Exception as e:
        logging.warning(f"시장 뉴스 조회 실패: {e}")

    return results


def collect_economic_calendar():
    """경제지표 캘린더 (schedule_override.json + 정적 일정)

    Finnhub Calendar는 유료이므로, 로컬 스케줄 파일을 참조한다.
    schedule_reports.py가 관리하는 schedule_override.json에서 당일 이벤트를 추출.

    Returns:
        list: [{event, time, impact}]
    """
    events = []
    override_file = os.path.join(BASE_DIR, "schedule_override.json")

    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).strftime("%Y-%m-%d")

    if os.path.exists(override_file):
        try:
            with open(override_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("overrides", []):
                if item.get("new_date", "") == today:
                    events.append({
                        "event": item.get("name", ""),
                        "time": item.get("new_time", ""),
                        "impact": item.get("impact", ""),
                    })
            for item in data.get("additions", []):
                if item.get("date", "") == today:
                    events.append({
                        "event": item.get("name", ""),
                        "time": item.get("time", ""),
                        "impact": item.get("impact", ""),
                    })
        except Exception as e:
            logging.warning(f"스케줄 오버라이드 읽기 실패: {e}")

    return events


def collect_rss_feeds():
    """RSS 피드 수집 (메르 블로그 등)

    Returns:
        list: [{title, date, source}]
    """
    feeds = [
        ("메르 블로그", "https://rss.blog.naver.com/ranto28"),
    ]
    results = []
    kst = timezone(timedelta(hours=9))
    cutoff = datetime.now(kst) - timedelta(hours=6)  # 최근 6시간

    for name, url in feeds:
        try:
            import urllib.request
            import xml.etree.ElementTree as ET
            from email.utils import parsedate_to_datetime

            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read().decode("utf-8")

            root = ET.fromstring(data)
            items = root.find("channel").findall("item")

            for item in items:
                title = item.find("title").text or ""
                pub_str = item.find("pubDate").text if item.find("pubDate") is not None else ""
                try:
                    pub_dt = parsedate_to_datetime(pub_str)
                    if pub_dt < cutoff:
                        continue
                    results.append({
                        "title": title,
                        "date": pub_dt.strftime("%Y-%m-%d %H:%M"),
                        "source": name,
                    })
                except Exception:
                    pass
        except Exception as e:
            logging.warning(f"RSS 수집 실패 ({name}): {e}")

    return results


# ─── 이벤트 추적 ───

def check_upcoming_events():
    """다가오는 업계 이벤트/실적 발표 확인 (D-14 이내)

    Returns:
        list: [{name, type, tickers, days_until, note}]
    """
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst)
    current_month = today.month
    current_day = today.day
    alerts = []

    # 1. 정적 이벤트 캘린더
    for event in INDUSTRY_EVENTS:
        event_month = event.get("month", 0)
        if event_month == 0:
            continue  # 반복 이벤트 (FOMC 등)는 별도 처리

        # 이번 달 또는 다음 달 이벤트만
        if event_month == current_month or event_month == (current_month % 12) + 1:
            event_day = event.get("day", 15)  # 일자 미지정 시 중순 가정
            try:
                event_date = today.replace(month=event_month, day=event_day)
            except ValueError:
                continue
            days_until = (event_date.date() - today.date()).days

            if 0 <= days_until <= 14:
                tickers = event.get("tickers", [])
                ticker_names = []
                for t in tickers:
                    if t == "_ALL":
                        ticker_names.append("전체")
                    else:
                        ticker_names.append(TICKER_NAMES.get(t, t))

                alerts.append({
                    "type": "industry_event",
                    "name": event["name"],
                    "event_type": event.get("type", "conference"),
                    "tickers": tickers,
                    "ticker_names": ticker_names,
                    "days_until": days_until,
                    "note": event.get("note", ""),
                    "timestamp": today.strftime("%Y-%m-%d %H:%M"),
                })

    # 2. 실적 발표 (yfinance — 첫 실행 시만, 하루 1회)
    state = load_state()
    if state.get("earnings_checked") != today.strftime("%Y-%m-%d"):
        try:
            earnings = get_upcoming_earnings()
            for e in earnings:
                if e["days_until"] <= 14:
                    alerts.append({
                        "type": "earnings",
                        "name": f"{e['name']} 실적 발표",
                        "tickers": [e["ticker"]],
                        "ticker_names": [e["name"]],
                        "days_until": e["days_until"],
                        "date": e["date"],
                        "note": f"{e['date']} 실적 발표 예정",
                        "timestamp": today.strftime("%Y-%m-%d %H:%M"),
                    })
            state["earnings_checked"] = today.strftime("%Y-%m-%d")
            save_state(state)
        except Exception as e:
            logging.warning(f"실적 일정 조회 실패: {e}")

    # 정렬: 가까운 순
    alerts.sort(key=lambda x: x.get("days_until", 999))
    return alerts


# ─── 방향 전환 감지 ───

THESIS_FILE = os.path.join(BASE_DIR, "investment_thesis.json")
NEWS_REPORT_DIR = os.path.join(BASE_DIR, "보고서", "뉴스")


def load_thesis():
    """investment_thesis.json 로드"""
    if os.path.exists(THESIS_FILE):
        with open(THESIS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"tickers": {}}


def save_thesis(thesis):
    """investment_thesis.json 저장"""
    with open(THESIS_FILE, "w", encoding="utf-8") as f:
        json.dump(thesis, f, ensure_ascii=False, indent=2)


def check_direction_change(ticker, news_score, prices):
    """investment_thesis.json의 현재 direction과 비교하여 전환 여부 판단

    Returns:
        tuple: (changed: bool, prev_direction: str, new_direction: str)
    """
    thesis = load_thesis()
    current = thesis.get("tickers", {}).get(ticker, {})
    prev_direction = current.get("direction", "neutral")

    change_pct = prices.get(ticker, {}).get("change_pct", 0)

    new_direction = prev_direction  # 기본: 유지
    if news_score <= -3.0 and change_pct < -3.0:
        new_direction = "bearish"
    elif news_score >= 3.0 and change_pct > 3.0:
        new_direction = "bullish"
    elif news_score <= -2.0 and prev_direction == "bullish":
        new_direction = "bearish"  # 강세→약세 전환
    elif news_score >= 2.0 and prev_direction == "bearish":
        new_direction = "bullish"  # 약세→강세 전환

    changed = new_direction != prev_direction
    return changed, prev_direction, new_direction


def handle_direction_changes(news, prices, state):
    """모든 종목의 방향 전환 감지 + 리포트 생성

    Returns:
        list: 방향 전환 정보 [{ticker, prev, new, score, change_pct}]
    """
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    changes = []

    for ticker, ndata in news.items():
        if ticker.startswith("_"):
            continue
        score = ndata.get("score", 0)
        if score == 0:
            continue

        changed, prev_dir, new_dir = check_direction_change(ticker, score, prices)
        name = TICKER_NAMES.get(ticker, ticker)
        change_pct = prices.get(ticker, {}).get("change_pct", 0)

        if changed:
            changes.append({
                "ticker": ticker,
                "name": name,
                "prev": prev_dir,
                "new": new_dir,
                "score": score,
                "change_pct": change_pct,
            })

            # investment_thesis.json 업데이트
            thesis = load_thesis()
            if ticker in thesis.get("tickers", {}):
                thesis["tickers"][ticker]["direction"] = new_dir
                thesis["tickers"][ticker]["last_change"] = now.strftime("%Y-%m-%d")
                thesis["tickers"][ticker]["change_reason"] = (
                    f"방향 전환 ({prev_dir}→{new_dir}): "
                    f"뉴스 점수 {score:+.1f}, 가격 {change_pct:+.1f}%"
                )
                save_thesis(thesis)
                logging.info(f"테제 업데이트: {ticker} {prev_dir}→{new_dir}")

            # news_report.py 호출 → 상세 리포트 생성
            try:
                report_script = os.path.join(BASE_DIR, "news_report.py")
                if os.path.exists(report_script):
                    # 뉴스 데이터를 임시 파일로 전달
                    report_data = {
                        "ticker": ticker,
                        "name": name,
                        "prev_direction": prev_dir,
                        "new_direction": new_dir,
                        "news_score": score,
                        "change_pct": change_pct,
                        "urgent": ndata.get("urgent", []),
                        "positive": ndata.get("positive", []),
                        "top_headlines": ndata.get("top_headlines", []),
                        "price": prices.get(ticker, {}).get("price", 0),
                        "timestamp": now.strftime("%Y-%m-%d %H:%M"),
                    }
                    trigger_file = os.path.join(DATA_DIR, ".news_report_trigger.json")
                    with open(trigger_file, "w", encoding="utf-8") as f:
                        json.dump(report_data, f, ensure_ascii=False, indent=2)

                    python = os.path.join(BASE_DIR, ".venv", "bin", "python3")
                    subprocess.Popen(
                        [python, report_script, trigger_file],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    logging.info(f"뉴스 리포트 생성 트리거: {ticker}")
            except Exception as e:
                logging.error(f"뉴스 리포트 트리거 실패 ({ticker}): {e}")

    return changes


# ─── 메인 로직 ───

def run_monitor():
    """1회 감시 실행"""
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    timestamp = now.strftime("%Y-%m-%d %H:%M")
    today = now.strftime("%Y-%m-%d")

    logging.info(f"=== 감시 시작 {timestamp} KST ===")

    state = load_state()

    # 일일 리셋
    if state.get("date") != today:
        state = {"date": today, "flash_cooldowns": {}, "daily_alerts": {}}

    open_markets = get_open_markets()
    active_tickers = get_active_tickers()

    logging.info(f"개장 시장: {open_markets or '없음'}")
    logging.info(f"감시 종목: {list(active_tickers.keys()) or '없음'}")

    # ─── 데이터 수집 ───

    # 1. 가격/거래량 (개장 시장만)
    prices = {}
    if active_tickers:
        prices = collect_prices(active_tickers)
        logging.info(f"가격 수집: {len(prices)}종목")

    # 2. 뉴스 (전 종목 — 장외 뉴스도 중요)
    news = collect_news(list(TICKER_MARKET.keys()))
    logging.info(f"뉴스 수집: {len(news)}종목")

    # 3. 경제 캘린더
    calendar = collect_economic_calendar()
    logging.info(f"경제지표: {len(calendar)}건")

    # 4. RSS
    rss = collect_rss_feeds()
    logging.info(f"RSS: {len(rss)}건")

    # ─── 이상 감지 + 임팩트 분류 ───

    triggers = []
    loss_alerts = []     # 🔴 손실 위험
    gain_alerts = []     # 🟢 수익 기회
    watch_alerts = []    # 🟡 주시

    # 가격 이상 → 임팩트 분류
    for ticker, pdata in prices.items():
        if pdata["alerts"]:
            alert_msg = ", ".join(pdata["alerts"])
            name = TICKER_NAMES.get(ticker, ticker)
            trigger = {
                "type": "price",
                "ticker": ticker,
                "name": name,
                "price": pdata["price"],
                "change_pct": pdata["change_pct"],
                "volume_ratio": pdata["vol_ratio"],
                "alerts": pdata["alerts"],
                "timestamp": timestamp,
            }
            triggers.append(trigger)

            line = f"*{name}* `{pdata['price']:,.2f}` ({pdata['change_pct']:+.1f}%) 거래량 {pdata['vol_ratio']:.1f}x"
            if pdata["change_pct"] <= -PRICE_CHANGE_THRESHOLD:
                loss_alerts.append(line)
            elif pdata["change_pct"] >= PRICE_CHANGE_THRESHOLD:
                gain_alerts.append(line)
            else:
                watch_alerts.append(line)
            logging.info(f"가격 알림: {ticker} {alert_msg}")

    # 텔레그램에 노출될 top 헤드라인만 모아 일괄 번역 (Haiku 1회 호출)
    headlines_to_translate = []
    for ticker, ndata in news.items():
        if ticker.startswith("_"):
            continue
        if ndata.get("urgent"):
            headlines_to_translate.append(ndata["urgent"][0].get("headline", ""))
        if ndata.get("positive"):
            headlines_to_translate.append(ndata["positive"][0].get("headline", ""))
    translations = translate_headlines(headlines_to_translate) if headlines_to_translate else {}

    # 뉴스 이상 → 임팩트 분류
    for ticker, ndata in news.items():
        if ticker.startswith("_"):
            continue
        name = TICKER_NAMES.get(ticker, ticker)

        # 부정 뉴스
        if ndata.get("urgent"):
            trigger = {
                "type": "news_loss",
                "ticker": ticker,
                "name": name,
                "urgent_count": len(ndata["urgent"]),
                "headlines": [u["headline"] for u in ndata["urgent"][:3]],
                "keywords": [u["keyword"] for u in ndata["urgent"][:3]],
                "score": ndata["score"],
                "timestamp": timestamp,
            }
            triggers.append(trigger)

            top = ndata["urgent"][0]
            head_kr = translations.get(top["headline"], top["headline"])
            url_line = f"\n   📎 {top['url']}" if top.get("url") else ""
            loss_alerts.append(
                f"🔴 *{name}* — {head_kr[:60]}\n   악재: {top['keyword']}{url_line}"
            )
            logging.info(f"손실 위험: {ticker} {top['keyword']}")

        # 긍정 뉴스
        if ndata.get("positive"):
            trigger = {
                "type": "news_gain",
                "ticker": ticker,
                "name": name,
                "positive_count": len(ndata["positive"]),
                "headlines": [p["headline"] for p in ndata["positive"][:3]],
                "score": ndata["score"],
                "timestamp": timestamp,
            }
            triggers.append(trigger)

            top = ndata["positive"][0]
            head_kr = translations.get(top["headline"], top["headline"])
            url_line = f"\n   📎 {top['url']}" if top.get("url") else ""
            gain_alerts.append(
                f"🟢 *{name}* — {head_kr[:60]}\n   호재: {top['keyword']}{url_line}"
            )
            logging.info(f"수익 기회: {ticker} {top['keyword']}")

    # 경제지표 이벤트
    for event in calendar:
        if event.get("impact") in ("HIGH", "high"):
            trigger = {
                "type": "economic",
                "event": event["event"],
                "impact": event["impact"],
                "timestamp": timestamp,
            }
            triggers.append(trigger)
            watch_alerts.append(f"*{event['event']}* ({event.get('time', '')} KST)")
            logging.info(f"경제지표: {event['event']}")

    # 업계 이벤트 / 실적 발표 D-7 알림
    event_alerts = check_upcoming_events()
    if event_alerts:
        triggers.extend(event_alerts)

    # ─── 방향 전환 감지 ───
    direction_changes = handle_direction_changes(news, prices, state)
    if direction_changes:
        logging.info(f"방향 전환 감지: {len(direction_changes)}건")

    # ─── 텔레그램 알림 (임팩트별 분류) ───
    has_alerts = loss_alerts or gain_alerts or watch_alerts or event_alerts or direction_changes

    if has_alerts:
        msg_parts = [f"*감시 알림* ({timestamp})"]

        # 방향 전환 (최우선 표시)
        if direction_changes:
            msg_parts.append("")
            msg_parts.append("🔄 *방향 전환 감지 — 리포트 생성 중*")
            for dc in direction_changes:
                arrow = "📈" if dc["new"] == "bullish" else "📉" if dc["new"] == "bearish" else "➡️"
                msg_parts.append(
                    f"{arrow} *{dc['name']}* ({dc['ticker']}): "
                    f"{dc['prev']}→{dc['new']} "
                    f"(뉴스 {dc['score']:+.1f}, 가격 {dc['change_pct']:+.1f}%)"
                )

        if loss_alerts:
            msg_parts.append("")
            msg_parts.append("🔴 *손실 위험 — 즉시 확인*")
            msg_parts.extend(loss_alerts[:5])

        if gain_alerts:
            msg_parts.append("")
            msg_parts.append("🟢 *수익 기회*")
            msg_parts.extend(gain_alerts[:5])

        if watch_alerts:
            msg_parts.append("")
            msg_parts.append("🟡 *주시*")
            msg_parts.extend(watch_alerts[:5])

        if event_alerts:
            msg_parts.append("")
            msg_parts.append("📅 *다가오는 이벤트*")
            for ea in event_alerts[:5]:
                d = ea.get("days_until", "?")
                prefix = "‼️" if d <= 3 else "📌" if d <= 7 else "📆"
                msg_parts.append(f"{prefix} D-{d} *{ea['name']}* — {ea.get('note', '')[:40]}")

        # 방향 유지 종목 요약 (뉴스 있는 종목만)
        maintained = []
        for ticker, ndata in news.items():
            if ticker.startswith("_"):
                continue
            if ndata.get("score", 0) != 0 and ticker not in [dc["ticker"] for dc in direction_changes]:
                thesis = load_thesis()
                direction = thesis.get("tickers", {}).get(ticker, {}).get("direction", "neutral")
                name = TICKER_NAMES.get(ticker, ticker)
                maintained.append(f"  {name}: 방향 유지 ({direction})")

        if maintained:
            msg_parts.append("")
            msg_parts.append("📋 *방향 유지*")
            msg_parts.extend(maintained[:5])

        send_telegram("\n".join(msg_parts))

    # ─── 이벤트 플래시 트리거 (손실 위험만) ───

    for trigger in triggers:
        ticker = trigger.get("ticker", trigger.get("event", "market"))
        if can_flash(ticker, state):
            # 가격 ±5% 이상 또는 긴급 뉴스 3건+ → 플래시
            should_flash = False
            if trigger["type"] == "price" and abs(trigger.get("change_pct", 0)) >= 5.0:
                should_flash = True
            elif trigger["type"] == "news" and trigger.get("urgent_count", 0) >= 2:
                should_flash = True
            elif trigger["type"] == "economic" and trigger.get("impact") == "high":
                should_flash = True

            if should_flash:
                trigger_event_flash(trigger)
                record_flash(ticker, state)

    # ─── 데이터 저장 ───

    snapshot = {
        "timestamp": timestamp,
        "open_markets": open_markets,
        "active_tickers": list(active_tickers.keys()),
        "prices": prices,
        "news": news,
        "calendar": calendar,
        "upcoming_events": [e for e in event_alerts] if event_alerts else [],
        "direction_changes": direction_changes,
        "rss": rss,
        "triggers": triggers,
        "trigger_count": len(triggers),
    }

    # 일별 파일에 추가 (append)
    daily_file = os.path.join(DATA_DIR, f"{today}.json")
    daily_data = []
    if os.path.exists(daily_file):
        try:
            with open(daily_file, "r", encoding="utf-8") as f:
                daily_data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            daily_data = []

    daily_data.append(snapshot)

    with open(daily_file, "w", encoding="utf-8") as f:
        json.dump(daily_data, f, ensure_ascii=False, indent=2)

    # 최신 스냅샷 (다른 스크립트에서 참조)
    latest_file = os.path.join(DATA_DIR, "latest.json")
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    # 상태 저장
    state["last_run"] = timestamp
    save_state(state)

    logging.info(f"=== 감시 완료: {len(triggers)}건 트리거 ===")

    # 30일 이상 된 데이터 정리
    _cleanup_old_data()

    return snapshot


def get_daily_summary(date=None):
    """일별 누적 데이터 요약 (보고서 입력용)

    Returns:
        dict: {date, snapshots, price_range, all_triggers, news_summary, calendar_events}
    """
    if date is None:
        kst = timezone(timedelta(hours=9))
        date = datetime.now(kst).strftime("%Y-%m-%d")

    daily_file = os.path.join(DATA_DIR, f"{date}.json")
    if not os.path.exists(daily_file):
        return None

    with open(daily_file, "r", encoding="utf-8") as f:
        snapshots = json.load(f)

    if not snapshots:
        return None

    # 종목별 가격 범위
    price_range = {}
    for snap in snapshots:
        for ticker, pdata in snap.get("prices", {}).items():
            if ticker not in price_range:
                price_range[ticker] = {"high": pdata["price"], "low": pdata["price"], "prices": []}
            price_range[ticker]["high"] = max(price_range[ticker]["high"], pdata["price"])
            price_range[ticker]["low"] = min(price_range[ticker]["low"], pdata["price"])
            price_range[ticker]["prices"].append(pdata["price"])

    # 전체 트리거
    all_triggers = []
    for snap in snapshots:
        all_triggers.extend(snap.get("triggers", []))

    # 뉴스 요약 (최신 스냅샷)
    latest_news = snapshots[-1].get("news", {})

    # 경제지표 (중복 제거)
    seen_events = set()
    calendar_events = []
    for snap in snapshots:
        for event in snap.get("calendar", []):
            key = event.get("event", "")
            if key not in seen_events:
                seen_events.add(key)
                calendar_events.append(event)

    return {
        "date": date,
        "snapshot_count": len(snapshots),
        "price_range": price_range,
        "all_triggers": all_triggers,
        "trigger_count": len(all_triggers),
        "news_summary": latest_news,
        "calendar_events": calendar_events,
        "rss": snapshots[-1].get("rss", []),
        "first_check": snapshots[0].get("timestamp", ""),
        "last_check": snapshots[-1].get("timestamp", ""),
    }


def format_daily_briefing(date=None):
    """Tier 1 데이터를 구조화된 텍스트 요약으로 변환 (Claude 프롬프트 주입용)

    raw JSON 대신 읽기 쉬운 텍스트를 반환하여 토큰 효율과 분석 활용도를 높인다.

    Returns:
        str: 구조화된 텍스트 요약. 데이터 없으면 'Tier 1 데이터 없음'
    """
    summary = get_daily_summary(date)
    if not summary:
        return "Tier 1 데이터 없음"

    lines = []
    lines.append(f"[Tier 1 감시 요약 — {summary['date']}]")
    first = summary.get('first_check', '')
    last = summary.get('last_check', '')
    # "2026-02-15 21:56" → "21:56"
    first_time = first.split(" ")[-1] if " " in first else first
    last_time = last.split(" ")[-1] if " " in last else last
    lines.append(f"감시: {summary['snapshot_count']}회 ({first_time}~{last_time})")
    lines.append("")

    # ─── 트리거 분류 ───
    triggers = summary.get("all_triggers", [])
    loss_triggers = []
    gain_triggers = []
    price_triggers = []
    volume_triggers = []
    event_triggers = []

    for t in triggers:
        ttype = t.get("type", "")
        if ttype == "price":
            price_triggers.append(t)
        elif ttype == "volume":
            volume_triggers.append(t)
        elif ttype == "industry_event" or ttype == "earnings":
            event_triggers.append(t)
        elif ttype == "news":
            score = t.get("score", 0)
            if score < 0:
                loss_triggers.append(t)
            elif score > 0:
                gain_triggers.append(t)

    def _get_headlines(t):
        """트리거에서 헤드라인/알림 목록 추출 (alerts 또는 headlines 키)"""
        return t.get("alerts", t.get("headlines", []))

    # 🔴 손실 위험
    if loss_triggers:
        lines.append(f"🔴 손실 위험 뉴스 ({len(loss_triggers)}건):")
        seen = set()
        for t in sorted(loss_triggers, key=lambda x: x.get("score", 0)):
            ticker = t.get("ticker", "?")
            name = TICKER_NAMES.get(ticker, ticker)
            headlines = _get_headlines(t)
            key = ticker  # 종목당 1줄로 중복 제거
            if key in seen:
                continue
            seen.add(key)
            score = t.get("score", 0)
            severity = "⚠️" if score >= -1 else "🚨" if score >= -2 else "💥"
            detail = headlines[0][:80] if headlines else "키워드 감지"
            lines.append(f"  {severity} {name}({ticker}): {detail}")
        lines.append("")

    # 🟢 수익 기회
    if gain_triggers:
        lines.append(f"🟢 수익 기회 뉴스 ({len(gain_triggers)}건):")
        seen = set()
        for t in sorted(gain_triggers, key=lambda x: -x.get("score", 0)):
            ticker = t.get("ticker", "?")
            name = TICKER_NAMES.get(ticker, ticker)
            headlines = _get_headlines(t)
            key = ticker
            if key in seen:
                continue
            seen.add(key)
            detail = headlines[0][:80] if headlines else "긍정 키워드 감지"
            lines.append(f"  💰 {name}({ticker}): {detail}")
        lines.append("")

    # 📈📉 가격 이상
    if price_triggers:
        lines.append(f"📈 가격 이상 ({len(price_triggers)}건):")
        for t in price_triggers:
            ticker = t.get("ticker", "?")
            name = TICKER_NAMES.get(ticker, ticker)
            headlines = _get_headlines(t)
            detail = ", ".join(headlines[:2]) if headlines else "가격 변동"
            lines.append(f"  {name}({ticker}): {detail}")
        lines.append("")

    # 📊 거래량 이상
    if volume_triggers:
        lines.append(f"📊 거래량 이상 ({len(volume_triggers)}건):")
        for t in volume_triggers:
            ticker = t.get("ticker", "?")
            name = TICKER_NAMES.get(ticker, ticker)
            headlines = _get_headlines(t)
            detail = ", ".join(headlines[:2]) if headlines else "거래량 급증"
            lines.append(f"  {name}({ticker}): {detail}")
        lines.append("")

    # 📅 다가오는 이벤트
    if event_triggers:
        lines.append(f"📅 다가오는 이벤트 ({len(event_triggers)}건):")
        seen_events = set()
        for t in sorted(event_triggers, key=lambda x: x.get("days_until", 99)):
            name = t.get("name", t.get("event", "?"))
            if name in seen_events:
                continue
            seen_events.add(name)
            days = t.get("days_until", "?")
            tickers = t.get("ticker_names", t.get("tickers", []))
            if isinstance(tickers, str):
                tickers = [tickers]
            ticker_str = ", ".join(tickers) if tickers else ""
            prefix = "‼️" if isinstance(days, int) and days <= 3 else "📌" if isinstance(days, int) and days <= 7 else "📆"
            note = t.get("note", "")
            lines.append(f"  {prefix} D-{days} {name} ({ticker_str}) — {note}")
        lines.append("")

    # 트리거가 하나도 없으면
    if not any([loss_triggers, gain_triggers, price_triggers, volume_triggers, event_triggers]):
        lines.append("특이사항 없음 — 모든 종목 정상 범위 내")
        lines.append("")

    # ─── 가격 범위 요약 (큰 변동만) ───
    price_range = summary.get("price_range", {})
    big_movers = []
    for ticker, pr in price_range.items():
        if pr["high"] > 0 and pr["low"] > 0:
            range_pct = (pr["high"] - pr["low"]) / pr["low"] * 100
            if range_pct >= 2.0:
                name = TICKER_NAMES.get(ticker, ticker)
                big_movers.append((name, ticker, pr["low"], pr["high"], range_pct))

    if big_movers:
        lines.append("장중 큰 변동 종목:")
        for name, ticker, lo, hi, pct in sorted(big_movers, key=lambda x: -x[4]):
            lines.append(f"  {name}({ticker}): ${lo:.2f}~${hi:.2f} (범위 {pct:.1f}%)")
        lines.append("")

    # ─── 경제지표 ───
    cal_events = summary.get("calendar_events", [])
    if cal_events:
        lines.append(f"경제지표 ({len(cal_events)}건):")
        for ev in cal_events:
            lines.append(f"  {ev.get('event', '?')}: 실제={ev.get('actual', '?')}, 예상={ev.get('estimate', '?')}, 직전={ev.get('prev', '?')}")
        lines.append("")

    # ─── RSS 헤드라인 요약 (상위 5개) ───
    rss = summary.get("rss", [])
    if rss:
        lines.append(f"주요 헤드라인 (RSS {len(rss)}건 중 상위):")
        for item in rss[:5]:
            title = item.get("title", "?")
            source = item.get("source", "?")
            lines.append(f"  [{source}] {title}")
        lines.append("")

    return "\n".join(lines)


def _cleanup_old_data():
    """30일 이상 된 모니터 데이터 삭제"""
    cutoff = datetime.now() - timedelta(days=30)
    for fname in os.listdir(DATA_DIR):
        if not fname.endswith(".json") or fname in ("latest.json",):
            continue
        try:
            fdate = datetime.strptime(fname[:10], "%Y-%m-%d")
            if fdate < cutoff:
                os.remove(os.path.join(DATA_DIR, fname))
                logging.info(f"오래된 데이터 삭제: {fname}")
        except ValueError:
            pass


# ─── CLI ───

def main():
    if "--daemon" in sys.argv:
        logging.info("데몬 모드 시작 (30분 간격)")
        while True:
            try:
                run_monitor()
            except Exception as e:
                logging.error(f"감시 오류: {e}")
            time.sleep(1800)  # 30분
    else:
        snapshot = run_monitor()
        print(f"\n감시 완료: {snapshot['trigger_count']}건 트리거")
        print(f"데이터: {os.path.join(DATA_DIR, snapshot['timestamp'][:10] + '.json')}")


if __name__ == "__main__":
    main()
