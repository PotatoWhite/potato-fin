#!/usr/bin/env python3
"""Finnhub 뉴스 센티먼트 분석 모듈

company_news + 키워드 점수 기반 센티먼트 계산.
backtest v6 및 일일 보고서에서 사용.

사용법:
  python3 news_sentiment.py              # 보유 종목 현재 센티먼트 출력
  python3 news_sentiment.py --backtest   # 백테스트용 프리페치 테스트
"""

import json
import os
import time
from datetime import datetime, timedelta

import finnhub

# API 키: .env 파일 또는 환경변수에서 로드
def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

_load_env()
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

NEWS_WINDOW_DAYS = 7       # 뉴스 집계 윈도우
NEWS_DECAY_DAYS = 3        # 풀웨이트 기간 (이후 50% 감쇠)
CHUNK_DAYS = 30            # API 호출 청크 크기

# 비미국 티커 접미사 (Finnhub 미지원)
NON_US_SUFFIXES = ('.KS', '.KQ', '.T', '.DE', '.L', '.HK')

# ─── 키워드 사전 ───

NEGATIVE_KEYWORDS = {
    # 심각 (-3)
    "DOJ investigation": -3, "DOJ probe": -3, "DOJ lawsuit": -3,
    "SEC investigation": -3, "SEC probe": -3, "SEC charges": -3,
    "fraud allegation": -3, "indictment": -3, "criminal charges": -3,
    "CEO fired": -3, "CEO resign": -3, "accounting fraud": -3,
    "files for bankruptcy": -3, "bankruptcy filing": -3,
    "Ponzi": -3, "embezzlement": -3,
    "data breach": -3, "massive recall": -3,
    # 높음 (-2)
    "class action": -2, "regulatory probe": -2,
    "FDA rejection": -2, "government shutdown": -2,
    "tariff increase": -2, "new tariff": -2, "trade war": -2,
    "sanctions": -2, "downgrade": -2, "guidance cut": -2,
    "profit warning": -2,
    "executive departure": -2, "layoff": -2, "recall": -2,
    "antitrust": -2, "monopoly probe": -2,
    # 보통 (-1)
    "lawsuit": -1, "investigation": -1, "probe": -1, "subpoena": -1,
    "earnings miss": -1, "below expectation": -1,
    "market share loss": -1, "disappointing": -1,
    "bearish": -1, "sell-off": -1, "selloff": -1,
    "shares drop": -1, "shares plunge": -1, "stock tumble": -1,
    "stocks tumble": -1, "shares fall": -1,
    "tariff": -1, "insider selling": -1,
}

POSITIVE_KEYWORDS = {
    # 강함 (+2)
    "FDA approval": +2, "breakthrough designation": +2,
    "record revenue": +2, "record earnings": +2,
    "beat expectation": +2, "beats expectation": +2, "topped estimate": +2,
    "raised guidance": +2, "raises guidance": +2,
    "stock buyback": +2, "dividend increase": +2,
    "acquisition approved": +2,
    # 보통 (+1)
    "upgraded to buy": +1, "upgrade": +1, "outperform": +1,
    "above expectation": +1, "bullish": +1,
    "strong demand": +1, "record high": +1, "all-time high": +1,
    "new contract": +1, "partnership": +1,
}

# 스캔들/위기 감지 키워드 (scandal_detected 판별용)
SCANDAL_KEYWORDS = [
    "DOJ", "SEC investigation", "SEC charges", "fraud allegation",
    "indictment", "criminal charges", "CEO fired", "CEO resign",
    "accounting fraud", "Ponzi", "embezzlement", "scandal",
    "bankruptcy filing", "files for bankruptcy",
]

# ─── v2 추가: 소스 신뢰도 ───

SOURCE_TIERS = {
    # Tier 1 (×1.5): 최고 신뢰
    "bloomberg": 1.5, "reuters": 1.5, "wsj": 1.5,
    "wall street journal": 1.5, "financial times": 1.5,
    "cnbc": 1.5, "ft.com": 1.5, "nytimes": 1.5,
    # Tier 2 (×1.0): 표준
    "yahoo": 1.0, "yahoo finance": 1.0, "marketwatch": 1.0,
    "seeking alpha": 1.0, "seekingalpha": 1.0, "barron": 1.0,
    "business insider": 1.0, "investor's business daily": 1.0,
    # Tier 3 (×0.5): 낮은 신뢰
    "benzinga": 0.5, "motley fool": 0.5, "investorplace": 0.5,
    "tipranks": 0.5, "24/7 wall st": 0.5, "zacks": 0.5,
    "thestreet": 0.5, "accesswire": 0.5, "globenewswire": 0.5,
    "prnewswire": 0.5, "businesswire": 0.5,
}

# ─── v2 추가: 부정어 리스트 ───

NEGATION_WORDS = {"not", "no", "denied", "failed", "cleared",
                  "dismissed", "acquitted", "without", "lack", "never"}

# ─── Rate Limiter ───

_call_times = []


def _rate_limit():
    """60콜/분 제한 (55콜 안전마진)"""
    global _call_times
    now = time.time()
    _call_times = [t for t in _call_times if now - t < 60]
    if len(_call_times) >= 55:
        sleep_time = 60 - (now - _call_times[0]) + 0.5
        if sleep_time > 0:
            time.sleep(sleep_time)
    _call_times.append(time.time())


# ─── API 함수 ───

def init_finnhub_client(api_key=None):
    """Finnhub 클라이언트 초기화"""
    key = api_key or FINNHUB_API_KEY
    return finnhub.Client(api_key=key)


def fetch_company_news(client, ticker, from_date, to_date):
    """종목별 뉴스 조회 (날짜 범위).

    Args:
        client: finnhub.Client
        ticker: 종목 티커 (US만 지원)
        from_date: "YYYY-MM-DD"
        to_date: "YYYY-MM-DD"

    Returns:
        list[dict]: 뉴스 기사 리스트 (빈 리스트 = 미지원/에러)
    """
    if any(ticker.endswith(s) for s in NON_US_SUFFIXES):
        return []
    _rate_limit()
    try:
        articles = client.company_news(ticker, _from=from_date, to=to_date)
        return articles if articles else []
    except Exception:
        return []


def fetch_general_news(client):
    """일반 시장 뉴스 조회 (정치/매크로)"""
    _rate_limit()
    try:
        return client.general_news('general', min_id=0) or []
    except Exception:
        return []


# ─── 키워드 점수 ───

def _get_source_weight(source):
    """소스 신뢰도 가중치 반환 (v2)"""
    if not source:
        return 0.8  # 소스 불명 시 기본 0.8
    src_lower = source.lower()
    for name, weight in SOURCE_TIERS.items():
        if name in src_lower:
            return weight
    return 0.8  # 매칭 안 되면 기본


def _check_negation(text, kw_pos):
    """키워드 위치 앞 3단어 내 부정어 존재 여부 (v2)"""
    # kw_pos 앞 텍스트에서 최근 3단어 추출
    prefix = text[:kw_pos].strip()
    words = prefix.split()[-3:]
    return any(w.lower().strip(",.;:") in NEGATION_WORDS for w in words)


def score_article(article):
    """단일 기사 키워드 점수 계산 (v2: 부정어 컨텍스트 + 소스 가중치).

    Returns:
        tuple: (score: float, scandal_kws: list[str])
    """
    text = (article.get("headline", "") + " " + article.get("summary", "")).lower()
    score = 0.0
    scandal_kws = []

    for kw, weight in NEGATIVE_KEYWORDS.items():
        kw_lower = kw.lower()
        pos = text.find(kw_lower)
        if pos >= 0:
            # 부정어 컨텍스트: 부정 키워드 앞에 부정어 → 긍정으로 반전
            if _check_negation(text, pos):
                score -= weight  # 부정의 부정 = 긍정
            else:
                score += weight

    for kw, weight in POSITIVE_KEYWORDS.items():
        kw_lower = kw.lower()
        pos = text.find(kw_lower)
        if pos >= 0:
            # 부정어 컨텍스트: 긍정 키워드 앞에 부정어 → 부정으로 반전
            if _check_negation(text, pos):
                score -= weight  # 긍정의 부정 = 부정
            else:
                score += weight

    for kw in SCANDAL_KEYWORDS:
        if kw.lower() in text:
            scandal_kws.append(kw)

    # 소스 가중치 적용
    source = article.get("source", "")
    source_weight = _get_source_weight(source)
    score *= source_weight

    return score, scandal_kws


def calc_news_score(articles, as_of_date=None):
    """뉴스 리스트 → 집계 센티먼트 점수.

    7일 윈도우, 3일 이내 풀웨이트 / 4~7일 50% 감쇠.
    기사 수 정규화 (많을수록 수확 체감).

    Returns:
        dict: score(-5~+5), article_count, negative_count, positive_count,
              top_negative, top_positive, scandal_detected, scandal_keywords
    """
    if as_of_date is None:
        ref = datetime.now()
    elif isinstance(as_of_date, str):
        ref = datetime.strptime(as_of_date[:10], "%Y-%m-%d")
    else:
        ref = as_of_date

    window_start = ref - timedelta(days=NEWS_WINDOW_DAYS)

    scored = []
    all_scandals = set()

    for a in articles:
        ts = a.get("datetime", 0)
        if ts == 0:
            continue
        dt = datetime.fromtimestamp(ts)
        if dt < window_start or dt > ref:
            continue

        raw, scandal_kws = score_article(a)
        age_days = (ref - dt).days
        decay = 1.0 if age_days <= NEWS_DECAY_DAYS else 0.5
        weighted = raw * decay

        scored.append({
            "headline": a.get("headline", ""),
            "raw": raw,
            "weighted": weighted,
            "dt": dt,
        })
        all_scandals.update(scandal_kws)

    if not scored:
        return {
            "score": 0.0,
            "article_count": 0,
            "negative_count": 0,
            "positive_count": 0,
            "top_negative": "",
            "top_positive": "",
            "scandal_detected": False,
            "scandal_keywords": [],
        }

    total = sum(s["weighted"] for s in scored)
    count = len(scored)

    # 정규화: 기사 수 체감 보정
    if count <= 3:
        norm = total
    elif count <= 10:
        norm = total * (3 + (count - 3) * 0.5) / count
    else:
        norm = total * (3 + 3.5 + (count - 10) * 0.2) / count

    # 스캔들 보너스: 심각한 뉴스가 있으면 추가 -1.0
    if all_scandals:
        norm -= 1.0

    final = max(-5.0, min(5.0, round(norm, 2)))

    neg_count = sum(1 for s in scored if s["raw"] < 0)
    pos_count = sum(1 for s in scored if s["raw"] > 0)

    sorted_neg = sorted(scored, key=lambda x: x["raw"])
    sorted_pos = sorted(scored, key=lambda x: x["raw"], reverse=True)
    top_neg = sorted_neg[0]["headline"] if sorted_neg and sorted_neg[0]["raw"] < 0 else ""
    top_pos = sorted_pos[0]["headline"] if sorted_pos and sorted_pos[0]["raw"] > 0 else ""

    # 소스 분포 집계
    source_counts = {}
    for a in articles:
        src = a.get("source", "Unknown")
        source_counts[src] = source_counts.get(src, 0) + 1

    return {
        "score": final,
        "article_count": count,
        "negative_count": neg_count,
        "positive_count": pos_count,
        "top_negative": top_neg,
        "top_positive": top_pos,
        "scandal_detected": bool(all_scandals),
        "scandal_keywords": sorted(all_scandals),
        "source_counts": source_counts,
    }


def calc_analyst_component(ticker):
    """애널리스트 컨센서스 점수 [-1, +1] (v2 추가 컴포넌트)

    yfinance recommendationMean + 목표가 괴리 사용.
    기존 fundamental에서 이동, 센티먼트에 통합.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info
    except Exception:
        return {"score": 0, "details": "N/A", "ib_warning": False}

    score = 0.0
    parts = []
    ib_warning = False

    rec_mean = info.get("recommendationMean")
    if rec_mean is not None:
        if rec_mean <= 1.5:
            score += 1.0
            parts.append(f"컨센 {rec_mean:.1f} Strong Buy")
        elif rec_mean <= 2.5:
            score += 0.5
            parts.append(f"컨센 {rec_mean:.1f} Buy")
        elif rec_mean >= 3.5:
            score -= 0.5
            parts.append(f"컨센 {rec_mean:.1f} Sell")
        else:
            parts.append(f"컨센 {rec_mean:.1f} Hold")
        # IB 관계 경고
        num_analysts = info.get("numberOfAnalystOpinions", 0)
        if num_analysts and num_analysts > 10:
            ib_warning = True

    # 목표가 괴리
    target = info.get("targetMeanPrice")
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if target and price and price > 0:
        upside = (target - price) / price * 100
        if upside > 30:
            score += 0.5
            parts.append(f"목표가 +{upside:.0f}%")
        elif upside < -10:
            score -= 0.5
            parts.append(f"목표가 {upside:.0f}%")

    score = max(-1, min(1, round(score, 1)))
    return {
        "score": score,
        "details": "; ".join(parts) if parts else "N/A",
        "ib_warning": ib_warning,
    }


def calc_news_score_v2(articles, ticker=None, as_of_date=None):
    """뉴스 센티먼트 v2: 키워드 + 소스 가중치 + 부정어 + 애널리스트

    기존 calc_news_score에 애널리스트 컴포넌트를 합산.
    범위: -5 ~ +5
    """
    base = calc_news_score(articles, as_of_date=as_of_date)

    # 애널리스트 컴포넌트
    analyst = {"score": 0, "details": "N/A", "ib_warning": False}
    if ticker:
        analyst = calc_analyst_component(ticker)

    combined = base["score"] + analyst["score"]
    final = max(-5.0, min(5.0, round(combined, 2)))

    return {
        **base,
        "score": final,
        "keyword_score": base["score"],
        "analyst_score": analyst["score"],
        "analyst_details": analyst["details"],
        "ib_warning": analyst["ib_warning"],
    }


# ─── 백테스트용 Prefetch ───

def prefetch_news_data(client, ticker, start_date, end_date):
    """백테스트 전체 기간 뉴스 프리페치 (30일 청크 + 디스크 캐시).

    과거 뉴스는 변하지 않으므로 한번 조회하면 보고서/news/cache/에 저장.
    재실행 시 캐시에서 로드하여 API 호출 최소화.

    캐시: 보고서/news/cache/{ticker}_{YYYY-MM}.json (월별)

    Args:
        client: finnhub.Client
        ticker: 종목 티커
        start_date: "YYYY-MM-DD" (백테스트 시작 - 7일)
        end_date: "YYYY-MM-DD" (백테스트 종료)

    Returns:
        list[dict]: 전체 기간 뉴스 (날짜순 정렬)
    """
    if any(ticker.endswith(s) for s in NON_US_SUFFIXES):
        return []

    cache_dir = os.path.join(NEWS_DIR, "cache")
    os.makedirs(cache_dir, exist_ok=True)

    all_news = []
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS), end)
        from_str = cursor.strftime("%Y-%m-%d")
        to_str = chunk_end.strftime("%Y-%m-%d")

        # 월별 캐시 키: 과거 월은 완전히 고정, 당월은 재조회
        month_key = cursor.strftime("%Y-%m")
        cache_file = os.path.join(cache_dir, f"{ticker}_{month_key}.json")
        is_current_month = (cursor.year == datetime.now().year
                            and cursor.month == datetime.now().month)

        if os.path.exists(cache_file) and not is_current_month:
            # 과거 월: 캐시에서 로드
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
            all_news.extend(cached)
        else:
            # 새로 조회
            articles = fetch_company_news(client, ticker, from_str, to_str)
            all_news.extend(articles)
            # 캐시 저장 (headline/datetime/source/summary만)
            slim = [
                {k: a.get(k, "") for k in ("headline", "datetime", "source", "summary", "related")}
                for a in articles
            ]
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(slim, f, ensure_ascii=False)

        cursor = chunk_end + timedelta(days=1)

    # 날짜순 정렬 (오래된 것 먼저)
    all_news.sort(key=lambda a: a.get("datetime", 0))
    return all_news


def calc_historical_news_score_fast(prefetched_news, as_of_date):
    """프리페치된 뉴스에서 특정 날짜 센티먼트 점수 계산.

    prefetch_news_data() 결과를 받아 as_of_date 기준 7일 윈도우 필터 후 점수 산출.

    Args:
        prefetched_news: list[dict] from prefetch_news_data()
        as_of_date: "YYYY-MM-DD"

    Returns:
        float: 센티먼트 점수 (-5 ~ +5)
    """
    if not prefetched_news:
        return 0.0

    result = calc_news_score(prefetched_news, as_of_date=as_of_date)
    return result["score"]


# ─── 보고서용 현재 센티먼트 ───

def fetch_current_sentiment(client, tickers, force=False):
    """보유 종목 현재 뉴스 센티먼트 일괄 조회.

    당일 이미 조회/저장된 데이터가 있으면 캐시에서 로드 (force=True로 강제 재조회).

    Args:
        client: finnhub.Client
        tickers: list[str]
        force: 캐시 무시하고 재조회

    Returns:
        dict: {
            ticker: {"news_score": dict, "articles": list},
            "_market": {"sentiment": dict, "articles": list}
        }
    """
    today = datetime.now().strftime("%Y-%m-%d")

    # 당일 캐시 확인
    if not force:
        cached = load_news(today)
        if cached:
            # 저장 형식 → 원래 형식으로 변환
            result = {}
            for ticker, data in cached.get("tickers", {}).items():
                result[ticker] = {
                    "news_score": {
                        "score": data.get("score", 0),
                        "article_count": data.get("count", 0),
                        "negative_count": data.get("negative", 0),
                        "positive_count": data.get("positive", 0),
                        "top_negative": data.get("top_negative", ""),
                        "top_positive": data.get("top_positive", ""),
                        "scandal_detected": data.get("scandal", False),
                        "scandal_keywords": data.get("scandal_keywords", []),
                    },
                    "articles": data.get("articles", []),
                }
            mkt = cached.get("_market", {})
            result["_market"] = {
                "sentiment": {
                    "score": mkt.get("score", 0),
                    "article_count": mkt.get("count", 0),
                    "scandal_detected": mkt.get("scandal", False),
                },
                "articles": mkt.get("articles", []),
            }
            return result

    week_ago = (datetime.now() - timedelta(days=NEWS_WINDOW_DAYS)).strftime("%Y-%m-%d")
    result = {}

    for ticker in tickers:
        articles = fetch_company_news(client, ticker, week_ago, today)
        ns = calc_news_score(articles)
        # 영향력 큰 기사 상위 5건
        top5 = sorted(articles, key=lambda a: abs(score_article(a)[0]), reverse=True)[:5]
        result[ticker] = {
            "news_score": ns,
            "articles": [{"headline": a.get("headline", ""), "source": a.get("source", "")} for a in top5],
        }

    # 매크로/정치 뉴스
    gen_articles = fetch_general_news(client)
    market_score = calc_news_score(gen_articles)
    top5_gen = sorted(gen_articles, key=lambda a: abs(score_article(a)[0]), reverse=True)[:5]
    result["_market"] = {
        "sentiment": market_score,
        "articles": [{"headline": a.get("headline", ""), "source": a.get("source", "")} for a in top5_gen],
    }

    # 자동 저장
    save_news(today, result)

    return result


# ─── 뉴스 저장/로드 ───

NEWS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "보고서", "news")
NEWS_RETENTION_DAYS = 90  # 90일 보관 후 자동 삭제


def save_news(date_str, data):
    """뉴스 데이터를 보고서/news/YYYY-MM-DD.json에 저장.

    저장 구조:
    {
        "date": "2026-02-11",
        "saved_at": "2026-02-11T20:30:00",
        "tickers": {
            "NVDA": {"score": +2.6, "count": 249, "articles": [...]},
            ...
        },
        "_market": {"score": -3.9, "count": 100, "articles": [...]},
        "_summary": {"avg_score": -0.8, "scandal_tickers": ["UNH"]}
    }

    저장 기준:
    - 일별 1개 파일 (같은 날 재실행 시 덮어쓰기)
    - 90일 보관 후 자동 삭제
    - articles는 headline/source/datetime/summary만 저장 (이미지/URL 제외)
    """
    os.makedirs(NEWS_DIR, exist_ok=True)
    filepath = os.path.join(NEWS_DIR, f"{date_str}.json")

    # articles에서 필요한 필드만 추출
    clean = {
        "date": date_str,
        "saved_at": datetime.now().isoformat()[:19],
        "tickers": {},
        "_market": {},
        "_summary": {},
    }

    scandal_tickers = []
    scores = []

    for key, val in data.items():
        if key == "_market":
            ns = val.get("sentiment", val.get("news_score", {}))
            clean["_market"] = {
                "score": ns.get("score", 0),
                "count": ns.get("article_count", 0),
                "scandal": ns.get("scandal_detected", False),
                "articles": [
                    {k: a[k] for k in ("headline", "source") if k in a}
                    for a in val.get("articles", [])[:10]
                ],
            }
        elif key.startswith("_"):
            continue
        else:
            ns = val.get("news_score", {})
            score = ns.get("score", 0)
            scores.append(score)
            if ns.get("scandal_detected"):
                scandal_tickers.append(key)
            clean["tickers"][key] = {
                "score": score,
                "count": ns.get("article_count", 0),
                "negative": ns.get("negative_count", 0),
                "positive": ns.get("positive_count", 0),
                "scandal": ns.get("scandal_detected", False),
                "scandal_keywords": ns.get("scandal_keywords", []),
                "top_negative": ns.get("top_negative", ""),
                "top_positive": ns.get("top_positive", ""),
                "articles": [
                    {k: a[k] for k in ("headline", "source") if k in a}
                    for a in val.get("articles", [])[:10]
                ],
            }

    clean["_summary"] = {
        "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
        "scandal_tickers": scandal_tickers,
        "total_tickers": len(scores),
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)

    # 자동 정리: 90일 이상 된 파일 삭제
    _cleanup_old_news()

    return filepath


def load_news(date_str):
    """저장된 뉴스 데이터 로드. 없으면 None."""
    filepath = os.path.join(NEWS_DIR, f"{date_str}.json")
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _cleanup_old_news():
    """90일 이상 된 뉴스 파일 삭제."""
    if not os.path.exists(NEWS_DIR):
        return
    cutoff = datetime.now() - timedelta(days=NEWS_RETENTION_DAYS)
    for fname in os.listdir(NEWS_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            fdate = datetime.strptime(fname[:10], "%Y-%m-%d")
            if fdate < cutoff:
                os.remove(os.path.join(NEWS_DIR, fname))
        except ValueError:
            pass


# ─── CLI ───

def main():
    from technical_analysis import get_portfolio_tickers

    client = init_finnhub_client()
    holdings = get_portfolio_tickers()
    tickers = sorted(holdings.keys())

    print("=" * 60)
    print("Finnhub 뉴스 센티먼트 분석")
    print("=" * 60)

    today = datetime.now().strftime("%Y-%m-%d")

    # 전체 센티먼트 1회 조회
    sentiment = fetch_current_sentiment(client, tickers)

    # 종목별 출력
    for ticker in tickers:
        name = holdings[ticker]["name"]
        data = sentiment.get(ticker, {})
        ns = data.get("news_score", {})
        if not ns or ns.get("article_count", 0) == 0:
            print(f"\n  {ticker:10s} ({name})")
            print(f"    뉴스 점수: +0.0 | 기사 0건 (비미국/ETF)")
            continue

        scandal_mark = " *** 스캔들!" if ns.get("scandal_detected") else ""
        print(f"\n  {ticker:10s} ({name})")
        print(f"    뉴스 점수: {ns['score']:+.1f} | 기사 {ns['article_count']}건 "
              f"(부정 {ns['negative_count']} / 긍정 {ns['positive_count']}){scandal_mark}")
        if ns.get("scandal_keywords"):
            print(f"    스캔들 키워드: {', '.join(ns['scandal_keywords'])}")
        if ns.get("top_negative"):
            print(f"    최악: {ns['top_negative'][:80]}")
        if ns.get("top_positive"):
            print(f"    최선: {ns['top_positive'][:80]}")

    # 매크로
    print(f"\n{'─' * 60}")
    ms = sentiment.get("_market", {}).get("sentiment", {})
    print(f"  매크로 센티먼트: {ms.get('score', 0):+.1f} | 기사 {ms.get('article_count', 0)}건")
    if ms.get("top_negative"):
        print(f"    최악: {ms['top_negative'][:80]}")
    if ms.get("top_positive"):
        print(f"    최선: {ms['top_positive'][:80]}")

    # 저장
    filepath = save_news(today, sentiment)
    print(f"\n  저장됨: {filepath}")


if __name__ == "__main__":
    main()
