---
name: naver-finance
description: 네이버 증권 API (한국/미국/일본 주식 + 환율 + 지수 + 거래원 + 외국인 보유율) 활용 가이드. 한국 주식 관련 시세/수급/펀더멘탈 데이터 조회 시 사용. `naver_finance.py` 래퍼 우선 활용.
---

# 네이버 증권 API Skill

potato-fin 프로젝트는 **네이버 API를 우선 사용** (사용자 지시 2026-04-21). yfinance는 네이버 미지원(독일 등) 시 fallback.

## 언제 이 skill 사용

- 한국 주식 (코스피/코스닥) 데이터 조회 — 가격/외국인/거래원/펀더멘탈
- 해외 주식 (미국/일본) 실시간 시세
- 환율 시계열 (USD/JPY/EUR ↔ KRW)
- KOSPI/KOSDAQ/KPI200 지수
- **"외국인 매수/매도", "기관 순매수", "거래원", "외인 보유율" 같은 키워드** 나오면 무조건 발동

## 🎯 가장 중요한 엔드포인트 3개 (외워둘 것)

### 1. 한국 통합정보 — 펀더멘탈 + 수급 한 방에
```
GET https://m.stock.naver.com/api/stock/{code}/integration
```
응답:
- `totalInfos[]` → PER/EPS/PBR/BPS/배당수익률/시총/외국인소진율/52주
- `dealTrendInfos[]` → 일별 외인/기관/개인 순매수 + 외인 보유율

### 2. 한국 일봉 + 외국인 보유율
```
GET https://api.stock.naver.com/chart/domestic/item/{code}/day?startDateTime=YYYYMMDDHHMM&endDateTime=YYYYMMDDHHMM
```
필드: `closePrice`, `foreignRetentionRate` (외국인 보유율 %)

### 3. 거래원 TOP5 (외국계 vs 국내 구분) — HTML 파싱
```
GET https://finance.naver.com/item/frgn.naver?code={code}&trader_day={1|5|20|60}
```
⚠️ EUC-KR 인코딩. `nv01` CSS 클래스 = 외국계 창구 (JP모건/골드만). 20분 지연.

## Python 래퍼 — 이미 구현된 함수 사용

```python
from naver_finance import get_price, get_ohlcv, get_foreign_retention, get_market_status

# 현재가 (한국/미국/일본 자동, 독일은 yfinance fallback)
price = get_price("005930.KS")   # 219000.0
price = get_price("NVDA")        # 201.65
price = get_price("BAYN.DE")     # 40.47 (yfinance)

# 일봉 (한국은 외국인 보유율 컬럼 포함)
df = get_ohlcv("035420.KS", days=30)
# df.columns = [Open, High, Low, Close, Volume, ForeignPct]

# 외국인 보유율 추이 (한국만)
fr = get_foreign_retention("035420.KS", days=14)
# fr["일별변화"] 파생 가능: fr["ForeignPct"].diff()

# 해외 거래소 정보
status = get_market_status("NVDA")
# {'exchange': 'NASDAQ', 'nation': '미국', 'delay_min': 0}
```

## 티커 변환 규칙 (yfinance → 네이버)

| yfinance | 네이버 | 시장 |
|----------|--------|------|
| 005930.KS | 005930 | KOSPI |
| 035420.KS | 035420 | KOSPI |
| 195940.KQ | 195940 | KOSDAQ |
| NVDA | NVDA.O | NASDAQ |
| UNH | UNH | NYSE (접미사 없음) |
| 1377.T | 1377.T | 도쿄 |
| BAYN.DE | ❌ 미지원 → yfinance | — |

래퍼의 `to_naver()` 함수가 자동 변환.

## 주의사항 (자주 실수)

1. **User-Agent 필수**: 모바일 Safari UA 권장
   ```python
   HEADERS = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"}
   ```
2. **EUC-KR**: `finance.naver.com/item/*` HTML 페이지는 EUC-KR. `response.encoding = 'euc-kr'` 필수
3. **Rate limit 없음 but 자제**: 2~5 req/sec 이하. 대량 조회 시 `time.sleep(0.3)`
4. **StockConflict 에러**: 종목 미지원 (주로 독일/프랑스). 즉시 fallback
5. **비공식 API**: 언제든 구조 변경. try/except + fallback 필수

## 네이버에 **없는** 데이터 (딴 데서 가져와야)

| 데이터 | 소스 | 방법 |
|--------|------|------|
| 공매도 잔고 | pykrx / KRX | `stock.get_shorting_status_by_date()` |
| 선물/옵션 | KIS OpenAPI | 별도 |
| 애널리스트 컨센서스 | FnGuide | 웹 스크래핑 |
| 독일/프랑스 주식 | yfinance | 자동 fallback |

## 확장 아이디어 (아직 구현 안 됨)

1. `get_fundamentals(ticker)` — integration API로 PER/PBR/EPS 반환
2. `get_investor_flow(ticker, days)` — 일별 외인/기관/개인 순매수 금액
3. `naver_broker.py` — 거래원 TOP5 파싱 (외국계/국내 구분)
4. `get_exchange_rate(pair, days)` — USD/JPY/EUR 환율 시계열
5. `get_kospi_ohlcv(days)` — KOSPI 지수 일봉

사용자가 이런 기능 필요하다고 하면 **완전한 가이드는 `docs/naver_api_guide.md`** 참조 (25개 엔드포인트 상세).

## 관련 파일

- `naver_finance.py` — Python 래퍼 (Phase 1 완료)
- `docs/naver_api_guide.md` — 완전한 레퍼런스 (25 엔드포인트)
- `market_data.py` — 기존 시장 데이터 모듈 (네이버 통합 예정)
- `주가_업데이트.py` — 포트폴리오 가격 조회 (네이버 통합 대상)
