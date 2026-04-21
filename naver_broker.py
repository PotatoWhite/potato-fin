"""
네이버 증권 거래원 TOP5 파서 — 외국계 vs 국내 창구 자동 구분.

엔드포인트: https://finance.naver.com/item/frgn.naver?code={code}&trader_day={1|5|20|60}
- 한국 주식 전용 (국내 상장 코드 6자리)
- HTML (EUC-KR) — iconv 또는 response.encoding='euc-kr' 필수
- 장중 20분 지연 데이터
- 인증 불필요

외국계 구분 로직:
- 매도/매수 창구 이름 셀(<td class="title">) 안에 <span class="nv01">가 있으면 외국계
- 예: <span class="nv01">제이피모간</span>, <span class="nv01">골드만삭스증권</span>, 씨티그룹, 모간스탠리
- 국내: span 없이 바로 텍스트 (신한투자증권, 키움증권, 미래에셋, NH투자증권 등)

활용:
- 보고서 수급 섹션에 "외국계 창구 순매수 -1.5억 (제이피모간 -3800주 + 씨티 -3400주)" 강제
- 셰이크아웃 체크: 외국인 보유율 +, 거래원 TOP5 외국계 → 진짜 매집
- 분배 체크: 뉴스 긍정인데 외국계 매도 상위 집중 → 추격 금지
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
)
HEADERS = {
    "User-Agent": UA,
    "Referer": "https://m.stock.naver.com/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
TIMEOUT = 10


def _to_krx_code(ticker: str) -> Optional[str]:
    """yfinance ticker (035420.KS) → krx 6자리 코드 (035420)."""
    if ticker.endswith((".KS", ".KQ")):
        return ticker.split(".")[0]
    if ticker.isdigit() and len(ticker) == 6:
        return ticker
    return None


def _parse_volume(text: str) -> int:
    """'37,941' 또는 '-136,875' 같은 문자열에서 정수 추출."""
    text = text.strip()
    if not text:
        return 0
    # 쉼표 제거, 음수 부호 유지
    cleaned = re.sub(r"[^\d\-]", "", text)
    if not cleaned or cleaned == "-":
        return 0
    try:
        return int(cleaned)
    except ValueError:
        return 0


def _extract_row(cells: list, offset: int) -> Optional[dict[str, Any]]:
    """
    매도/매수 한 쌍의 (title_td, num_td) 에서 창구 정보 추출.
    offset=0 매도측, offset=2 매수측.
    """
    if len(cells) < offset + 2:
        return None
    title_td = cells[offset]
    num_td = cells[offset + 1]

    # 빈 셀 (공백 유지용)
    if not title_td.text.strip():
        return None

    # 외국계 판정: title_td 안에 <span class="nv01">가 있으면 외국계
    foreign_span = title_td.select_one("span.nv01")
    is_foreign = foreign_span is not None

    # 창구 이름
    if foreign_span:
        broker_name = foreign_span.text.strip()
    else:
        broker_name = title_td.get_text(strip=True)

    if not broker_name:
        return None

    volume = _parse_volume(num_td.get_text())

    return {
        "broker": broker_name,
        "is_foreign": is_foreign,
        "volume": volume,
    }


def get_brokers(ticker: str, trader_day: int = 1) -> Optional[dict[str, Any]]:
    """
    종목별 거래원 TOP5 (매도/매수 각 5개).

    Args:
        ticker: 한국 종목 (035420.KS 또는 035420)
        trader_day: 1=당일, 5=5일, 20=20일, 60=60일 누적

    Returns:
        {
            "ticker": "035420",
            "trader_day": 1,
            "sell_top": [ {broker, is_foreign, volume}, ... ],   # 매도 상위 5
            "buy_top":  [ {broker, is_foreign, volume}, ... ],   # 매수 상위 5
            "summary": {
                "foreign_sell_volume": 72000,   # 외국계 매도 총합
                "foreign_buy_volume":  12000,
                "foreign_net":        -60000,   # 외국계 매수 - 매도 (음수 = 순매도)
                "domestic_sell_volume": 30000,
                "domestic_buy_volume":  88000,
                "domestic_net":         58000,
                "foreign_sell_count":   3,      # 매도 TOP5 중 외국계 수
                "foreign_buy_count":    1,
            }
        }
        None: 파싱 실패 or 해외 종목
    """
    if BeautifulSoup is None:
        logger.error("beautifulsoup4 미설치")
        return None

    code = _to_krx_code(ticker)
    if not code:
        logger.warning(f"한국 종목 코드 아님: {ticker}")
        return None

    if trader_day not in (1, 5, 20, 60):
        trader_day = 1

    url = f"https://finance.naver.com/item/frgn.naver?code={code}&trader_day={trader_day}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "euc-kr"
        html = r.text
    except Exception as e:
        logger.warning(f"naver frgn fetch failed for {code}: {e}")
        return None

    soup = BeautifulSoup(html, "html.parser")

    # 매도상위 + 매수상위 header가 있는 table 찾기
    target_table = None
    for table in soup.select("table.type2"):
        headers_text = " ".join(th.get_text(strip=True) for th in table.select("thead th, tr th"))
        if "매도상위" in headers_text and "매수상위" in headers_text:
            target_table = table
            break

    if target_table is None:
        logger.warning(f"거래원 table 찾을 수 없음: {code}")
        return None

    sell_top: list[dict[str, Any]] = []
    buy_top: list[dict[str, Any]] = []

    for tr in target_table.select("tbody tr"):
        cells = tr.select("td")
        # 구조: [매도창구 td, 매도량 td, 매수창구 td, 매수량 td]
        sell = _extract_row(cells, 0)
        buy = _extract_row(cells, 2)
        if sell:
            sell_top.append(sell)
        if buy:
            buy_top.append(buy)
        if len(sell_top) >= 5 and len(buy_top) >= 5:
            break

    if not sell_top and not buy_top:
        logger.warning(f"거래원 행 추출 실패: {code}")
        return None

    # 집계
    def _agg(lst):
        f_vol = sum(r["volume"] for r in lst if r["is_foreign"])
        d_vol = sum(r["volume"] for r in lst if not r["is_foreign"])
        f_cnt = sum(1 for r in lst if r["is_foreign"])
        return f_vol, d_vol, f_cnt

    f_sell, d_sell, f_sell_cnt = _agg(sell_top[:5])
    f_buy, d_buy, f_buy_cnt = _agg(buy_top[:5])

    summary = {
        "foreign_sell_volume": f_sell,
        "foreign_buy_volume": f_buy,
        "foreign_net": f_buy - f_sell,
        "domestic_sell_volume": d_sell,
        "domestic_buy_volume": d_buy,
        "domestic_net": d_buy - d_sell,
        "foreign_sell_count": f_sell_cnt,
        "foreign_buy_count": f_buy_cnt,
    }

    return {
        "ticker": code,
        "trader_day": trader_day,
        "sell_top": sell_top[:5],
        "buy_top": buy_top[:5],
        "summary": summary,
    }


def format_brokers(result: dict[str, Any]) -> str:
    """보고서용 한 줄 요약 + TOP5 표."""
    if not result:
        return "(거래원 데이터 없음)"
    s = result["summary"]
    label_day = {1: "당일", 5: "5일", 20: "20일", 60: "60일"}.get(result["trader_day"], "?")

    sign = "+" if s["foreign_net"] >= 0 else ""
    lines = [
        f"=== 거래원 TOP5 ({result['ticker']}, {label_day}) ===",
        f"외국계 순매수: {sign}{s['foreign_net']:,}주 (매수 {s['foreign_buy_volume']:,} - 매도 {s['foreign_sell_volume']:,})",
        f"국내 순매수:   {'+' if s['domestic_net']>=0 else ''}{s['domestic_net']:,}주",
        f"외국계 집중도: 매도 {s['foreign_sell_count']}/5 · 매수 {s['foreign_buy_count']}/5",
        "",
        "매도 TOP5          |  매수 TOP5",
        "-" * 55,
    ]
    for i in range(5):
        sell = result["sell_top"][i] if i < len(result["sell_top"]) else {}
        buy = result["buy_top"][i] if i < len(result["buy_top"]) else {}
        sell_tag = "🌍" if sell.get("is_foreign") else "🇰🇷"
        buy_tag = "🌍" if buy.get("is_foreign") else "🇰🇷"
        sell_str = f"{sell_tag} {sell.get('broker', '-'):10s} {sell.get('volume', 0):>7,}" if sell else " " * 25
        buy_str = f"{buy_tag} {buy.get('broker', '-'):10s} {buy.get('volume', 0):>7,}" if buy else ""
        lines.append(f"{sell_str}  |  {buy_str}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────
# CLI (self-test)
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Naver Broker 파서 self-test ===\n")

    test_tickers = [
        ("035420.KS", "NAVER"),
        ("005930.KS", "삼성전자"),
        ("000660.KS", "SK하이닉스"),
        ("195940.KQ", "HK이노엔"),
    ]

    for tk, name in test_tickers:
        print(f"\n### {tk} {name}")
        result = get_brokers(tk, trader_day=1)
        if result:
            print(format_brokers(result))
        else:
            print("  (데이터 없음)")
        print()

    print("\n=== 20일 누적 (035420 NAVER) ===")
    r20 = get_brokers("035420.KS", trader_day=20)
    if r20:
        print(format_brokers(r20))
