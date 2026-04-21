# 네이버 증권 API 가이드 — potato-fin 활용 레퍼런스

> **작성**: 2026-04-21
> **기준**: 실측 검증된 25개 비공식 엔드포인트
> **우선순위**: 사용자 지시 "가급적 naver API 우선" (2026-04-21)
> **관련 코드**: `naver_finance.py` (Python 래퍼)

---

## 0. 왜 네이버 API인가

| 비교 | yfinance | pykrx | **네이버 API** |
|------|---------|-------|---------------|
| 한국 주식 정확도 | 지연/누락 있음 | ✅ KRX 공식 | ✅ 거의 실시간 |
| **외국인 보유율 일별** | ❌ | 로그인 필요 | ✅ 차트 API 포함 |
| **거래원 TOP5 (외국계/국내 구분)** | ❌ | ❌ | ✅ HTML 파싱 |
| **일별 외인/기관/개인 순매수** | ❌ | 로그인 필요 | ✅ integration API |
| 해외 주식 (US/JP) | ✅ | ❌ | ✅ polling 실시간 |
| 독일 (BAYN.DE) | ✅ | ❌ | ❌ → yfinance fallback |
| 펀더멘탈 (PER/PBR/EPS) | 미국만 | 로그인 필요 | ✅ integration API (한국) |
| 환율 히스토리 | ✅ (USD만) | ❌ | ✅ USD/JPY/EUR/KRW |
| 인증 | API key | KRX 계정 | **불필요** |
| Rate limit | 200/hr | 없음 (로컬) | ~2-5 req/sec (경험치) |
| 비용 | 무료 | 무료 | 무료 |

**결론**: 한국 데이터는 네이버가 최강. 해외는 네이버 → yfinance fallback.

---

## 1. 엔드포인트 카탈로그 (검증 완료)

### 🇰🇷 한국 주식 — 핵심 3개

#### (1) 종목 통합정보 ⭐⭐⭐ (가장 가치 높음)
```
GET https://m.stock.naver.com/api/stock/{code}/integration
```
**한 번에 모든 것**: 펀더멘탈 + 3일치 수급 + 외국인 보유율

주요 응답 필드:
- `totalInfos[]` → PER, EPS, PBR, BPS, 배당수익률, 주당배당금, 시가총액, **외국인소진율**, 52주 최고/최저, 추정 PER, 추정 EPS
- `dealTrendInfos[]` → 일별 **외인 순매수량 + 기관 순매수량 + 개인 순매수량** + 외인 보유율 + 종가

```bash
curl -s -A "Mozilla/5.0 iPhone" "https://m.stock.naver.com/api/stock/005930/integration" | jq '.dealTrendInfos[:3]'
```

사용 예 (Python):
```python
import requests
r = requests.get(
    "https://m.stock.naver.com/api/stock/005930/integration",
    headers={"User-Agent": "Mozilla/5.0 iPhone"}
)
data = r.json()
for info in data.get("totalInfos", []):
    print(info.get("code"), info.get("value"))   # PER/PBR/EPS 등
for day in data.get("dealTrendInfos", []):
    print(day["bizdate"], day["foreignerPureBuyQuant"])
```

#### (2) 일봉 차트 + 외국인 보유율 ⭐⭐
```
GET https://api.stock.naver.com/chart/domestic/item/{code}/day?startDateTime=YYYYMMDDHHMM&endDateTime=YYYYMMDDHHMM
```

주요 응답 필드:
- `localDate`, `openPrice`, `highPrice`, `lowPrice`, `closePrice`
- `accumulatedTradingVolume`
- **`foreignRetentionRate`** (외국인 보유율 %)

사용 예:
```python
url = f"https://api.stock.naver.com/chart/domestic/item/035420/day?startDateTime=202604010000&endDateTime=202604220000"
rows = requests.get(url, headers=HEADERS).json()
# rows: list of dict
```

#### (3) 거래원 TOP5 (외국계 vs 국내 구분) ⭐⭐
```
GET https://finance.naver.com/item/frgn.naver?code={code}&trader_day={1|5|20|60}
```

⚠️ **HTML (EUC-KR)** — 반드시 `iconv -f EUC-KR` 또는 Python `response.encoding = 'euc-kr'`

핵심 포인트:
- **매도 상위 5 / 매수 상위 5** 창구
- CSS 클래스 `nv01` = **외국계 창구** (JP모건/골드만/모건스탠리 등)
- 기본색 = 국내 창구 (삼성증권/미래에셋/NH/키움 등)
- `trader_day=1` (당일), `5` (5일), `20` (20일 누적), `60` (60일 누적)

**주의**: 장중 **20분 지연**. 실시간 아님.

파싱 (Python):
```python
from bs4 import BeautifulSoup
r = requests.get(f"https://finance.naver.com/item/frgn.naver?code=035420&trader_day=1", headers=HEADERS)
r.encoding = 'euc-kr'
soup = BeautifulSoup(r.text, 'html.parser')

for row in soup.select("table.type2 tr"):
    cells = row.select("td")
    # nv01 = 외국계 구분
    is_foreign = any("nv01" in c.get("class", []) for c in cells)
    if cells and len(cells) >= 4:
        name = cells[0].text.strip()
        volume = cells[1].text.strip()
        label = "🌍 외국계" if is_foreign else "🇰🇷 국내"
        print(f"{label} {name}: {volume}")
```

---

### 🇰🇷 한국 — 보조 엔드포인트

#### (4) 기본정보 (m.stock 경로)
```
GET https://m.stock.naver.com/api/stock/{code}/basic
```
가격/이미지차트/업종/거래상태. 단순 시세만 필요할 때.

#### (5) 실시간 시세 (70초 폴링)
```
GET https://polling.finance.naver.com/api/realtime/domestic/stock/{code}
```
응답의 `pollingInterval: 70000` (70초 권장). 현재가 + 전일 대비.

#### (6) 일봉 (구 JSON API — 긴 기간 조회용)
```
GET https://api.finance.naver.com/siseJson.naver?symbol={code}&requestType=1&startTime=YYYYMMDD&endTime=YYYYMMDD&timeframe=day
```
- `timeframe=week/month` 지원 → 주봉/월봉도 가능
- 응답: `[날짜, 시가, 고가, 저가, 종가, 거래량, 외국인소진율]` 배열

#### (7) 일봉 (front-api 신규 경로)
```
GET https://m.stock.naver.com/front-api/external/chart/domestic/info?symbol={code}&requestType=1&startTime=...&endTime=...&timeframe=day
```
(6)의 새 버전. 응답 동일.

#### (8) 지수 일봉 (KOSPI/KOSDAQ/KPI200)
```
GET https://api.stock.naver.com/chart/domestic/index/{idx}/day?startDate=...&endDate=...
```
`idx`: `KOSPI`, `KOSDAQ`, `KPI200`

#### (9) 지수 실시간
```
GET https://polling.finance.naver.com/api/realtime/domestic/index/{idx}
```

#### (10) 공시
```
GET https://m.stock.naver.com/api/stock/{code}/disclosure
```
응답: `disclosureId`, `title`, `datetime`, `author (KOSCOM)` — DART 보완용

#### (11) 종목 토론방
```
GET https://finance.naver.com/item/board.naver?code={code}&page=N
```
HTML. 제목/작성자/일시/조회/공감. 긍부정 자체 분석 필요.

#### (12) 뉴스 / 공시 HTML
```
GET https://finance.naver.com/item/news_news.naver?code={code}
GET https://finance.naver.com/item/news_notice.naver?code={code}
```

#### (13) 재무제표 (FN가이드)
```
GET https://finance.naver.com/item/coinfo.naver?code={code}&target=finsum_more
```
HTML. 연간/분기 재무 테이블.

---

### 🌍 해외 주식

#### (14) 기본정보
```
GET https://api.stock.naver.com/stock/{ticker}/basic
```
- 티커 형식:
  - NASDAQ: `NVDA.O`, `GOOGL.O`, `TSLA.O`, `MSFT.O`
  - NYSE: `UNH`, `WRB`, `CVX` (접미사 없음)
  - 일본: `1377.T`
  - 독일: ❌ 미지원 (BAYN.DE 등)

#### (15) 실시간 시세 (7초 폴링)
```
GET https://polling.finance.naver.com/api/realtime/worldstock/stock/{ticker}
```
미국은 실시간 0분 지연, 일본은 15분 지연.

#### (16) 일봉 OHLCV
```
GET https://api.stock.naver.com/chart/foreign/item/{ticker}/day?startDate=YYYYMMDD&endDate=YYYYMMDD
```
yfinance 대체/백업 가능.

---

### 💱 환율 & 시장

#### (17) 환율 일별 시계열
```
GET https://api.stock.naver.com/marketindex/exchange/{fx}/prices?pageSize=N&page=1
```
- `fx`: `FX_USDKRW`, `FX_JPYKRW`, `FX_EURKRW`, `FX_CNYKRW`
- 응답: `localTradedAt`, `closePrice`, `fluctuations`, `cashBuy/Sell` 등

#### (18) 환율 실시간
```
GET https://api.stock.naver.com/marketindex/exchange/{fx}/basic
```

#### (19) 업종 / 테마 지수
```
GET https://finance.naver.com/sise/sise_group.naver?type=upjong   # 업종
GET https://finance.naver.com/sise/sise_group.naver?type=theme    # 테마
```
HTML. 업종별 등락률.

#### (20) 시가총액 랭킹 / 특징주
```
GET https://finance.naver.com/sise/sise_market_sum.naver?sosok=0  # KOSPI
GET https://finance.naver.com/sise/sise_market_sum.naver?sosok=1  # KOSDAQ
GET https://finance.naver.com/sise/sise_upper.naver               # 상한가
GET https://finance.naver.com/sise/sise_rising.naver              # 급등주
GET https://finance.naver.com/sise/sise_falling.naver             # 급락주
```

---

### 🔻 분봉 / 일별 시세 (구 HTML)

#### (21) 일별 시세 테이블
```
GET https://finance.naver.com/item/sise_day.naver?code={code}&page=N
```
pandas `read_html` 친화.

#### (22) 분봉 (당일 1분봉)
```
GET https://finance.naver.com/item/sise_time.naver?code={code}&thistime=YYYYMMDDHHMMSS&page=N
```

#### (23) 외인/기관 일별 순매매 페이지
```
GET https://finance.naver.com/item/frgn.naver?code={code}&page={1..N}
```
HTML. 날짜별 순매수/보유율 테이블. pykrx 대체 가능.

---

## 2. 한계 & 대안

### ❌ 네이버에 없는 데이터

| 데이터 | 네이버 상태 | 대안 |
|-------|------------|------|
| **공매도 잔고/일별** | HTML만 있고 KRX iframe 임베드 | **pykrx** `get_shorting_status_by_date` or KRX 직접 크롤 |
| **선물/옵션** | API 부재 | KRX 정보데이터시스템 (data.krx.co.kr) or **KIS OpenAPI** |
| **애널리스트 컨센서스** | 404 | FnGuide 웹 스크래핑 or 38커뮤니케이션 |
| **테마/업종 지수 JSON** | HTML만 | sise_group.naver 파싱 |
| **독일 주식** | StockConflict | **yfinance fallback** |

### ⚠ 주의사항

1. **EUC-KR 인코딩**: 구 `finance.naver.com/item/*` HTML 페이지는 EUC-KR. Python에서 `response.encoding = 'euc-kr'` 필수
2. **Rate limit**: 공식 문서 없음. 경험치 **2~5 req/sec** 이하 권장. `time.sleep(0.3)` 정도
3. **User-Agent 필수**: 빈 UA면 차단될 수 있음. 모바일 Safari 권장:
   ```
   Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1
   ```
4. **Referer**: `https://m.stock.naver.com/` 추가 시 안정적
5. **비공식 API**: 언제든 구조 변경 가능. 에러 처리 + fallback 필수

---

## 3. potato-fin 통합 전략

### 🎯 권장 경로

| 데이터 종류 | 우선순위 | 엔드포인트 | 모듈 |
|-----------|--------|-----------|------|
| 한국 주식 가격 | 1. 네이버 | chart/domestic/item | `naver_finance.get_ohlcv()` |
| 한국 외국인 보유율 | 1. 네이버 | chart/domestic + integration | `naver_finance.get_foreign_retention()` |
| 한국 일별 외인/기관 순매수 | 1. 네이버 | **integration** API | ⭐ 추가 필요 |
| 한국 거래원 TOP5 | 1. 네이버 | frgn.naver HTML 파싱 | ⭐ 추가 필요 (`naver_broker.py`) |
| 한국 펀더멘탈 (PER/PBR) | 1. 네이버 | **integration** API | ⭐ 추가 필요 |
| 한국 공매도 | 1. pykrx | get_shorting_status | 별도 모듈 |
| 미국 주식 | 1. 네이버 / 2. yfinance | basic + polling | `naver_finance.get_price()` |
| 일본 주식 | 1. 네이버 | basic + polling | 동일 |
| 독일 주식 | 1. yfinance | - | fallback 기본 |
| 환율 | 1. 네이버 | marketindex/exchange | ⭐ 추가 필요 |
| KOSPI/KOSDAQ 지수 | 1. 네이버 | chart/domestic/index | ⭐ 추가 필요 |

### 단계적 구현

**Phase 1 (완료)** — `naver_finance.py`
- `get_price()`, `get_ohlcv()`, `get_foreign_retention()`, `get_market_status()`
- 한국 5 + 해외 14 + BAYN.DE fallback

**Phase 2 (다음)** — integration API 통합
- `get_fundamentals(ticker)` — PER/PBR/EPS (한국)
- `get_investor_flow(ticker, days)` — 외인/기관/개인 일별 순매수 금액
- `get_foreign_exhaustion(ticker)` — 외인 소진율 (상장주식 대비)

**Phase 3** — 거래원 + 환율
- `naver_broker.py` — TOP5 실시간 (20분 지연)
- 환율 엔드포인트 통합

**Phase 4** — pykrx 보완 (공매도)
- `kr_short.py` — KRX 공매도 잔고 직접 크롤

---

## 4. 실전 curl 샘플 모음

```bash
UA="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"

# 1. 삼성전자 펀더멘탈 + 3일 수급 한 방에
curl -s -A "$UA" "https://m.stock.naver.com/api/stock/005930/integration" | jq .

# 2. NAVER 일봉 + 외인 보유율 (4월 전체)
curl -s -A "$UA" "https://api.stock.naver.com/chart/domestic/item/035420/day?startDateTime=202604010000&endDateTime=202604220000" | jq .

# 3. NVDA 실시간
curl -s -A "$UA" "https://polling.finance.naver.com/api/realtime/worldstock/stock/NVDA.O" | jq .

# 4. NVDA 일봉
curl -s -A "$UA" "https://api.stock.naver.com/chart/foreign/item/NVDA.O/day?startDate=20260101&endDate=20260421" | jq .

# 5. SK하이닉스 거래원 TOP5 (당일, 20분 지연)
curl -s -A "$UA" "https://finance.naver.com/item/frgn.naver?code=000660&trader_day=1" | iconv -f EUC-KR -t UTF-8 | grep -oE "(모건|골드만|씨티|UBS|삼성증권|미래에셋|NH투자|한국투자|키움)"

# 6. USD/KRW 30일 환율
curl -s -A "$UA" "https://api.stock.naver.com/marketindex/exchange/FX_USDKRW/prices?pageSize=30&page=1" | jq .

# 7. KOSPI 지수 30일
curl -s -A "$UA" "https://api.stock.naver.com/chart/domestic/index/KOSPI/day?startDate=20260301&endDate=20260421" | jq .

# 8. 공시
curl -s -A "$UA" "https://m.stock.naver.com/api/stock/005930/disclosure" | jq .
```

---

## 5. 참고 자료

- [FinanceData: Naver 재무제표 크롤링](https://financedata.github.io/posts/naver-finance-finstate-crawling.html)
- [pykrx (KRX+Naver 하이브리드) GitHub](https://github.com/sharebook-kr/pykrx)
- [corazzon/finance-data-analysis — 네이버금융 개별종목 노트북](https://github.com/corazzon/finance-data-analysis/blob/main/3.3%20%EB%84%A4%EC%9D%B4%EB%B2%84%EA%B8%88%EC%9C%B5%20%EA%B0%9C%EB%B3%84%EC%A2%85%EB%AA%A9%20%EC%88%98%EC%A7%91-input.ipynb)
- [LAB OF DAEGON: frgn.naver 크롤링 구조](https://ldgeao99.wordpress.com/2017/04/23/)
- [KnightChaser gist: Naver Finance unofficial methods](https://gist.github.com/KnightChaser/95e0a36bebc09008a9dbc8b90ec443f4)
- [maxmin93/naver-stocks-collector (Scrapy 전종목)](https://github.com/maxmin93/naver-stocks-collector)
- [nomorecoke/naver-finance-board-crawler](https://github.com/nomorecoke/naver-finance-board-crawler)

---

## 6. 갱신 이력

| 일자 | 변경 | 담당 |
|------|------|------|
| 2026-04-21 | 초판 작성, 25개 엔드포인트 검증. `naver_finance.py` Phase 1 완료 | Claude + Agent 발굴 |
