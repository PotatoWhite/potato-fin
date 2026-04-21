# 주식 포트폴리오 관리 시스템

## 프로젝트 구조

```
/home/bravopotato/Spaces/finspace/potato-fin/
├── CLAUDE.md              # 이 파일 (Claude 지시서)
├── portfolio_db.py        # 중앙 DB 모듈 (SECTOR, load_portfolio, get_tickers, get_cost_basis)
├── portfolio.db           # SQLite DB (trades + snapshots + realtime_prices)
├── 주가_업데이트.py          # 자동 주가 조회 + SQLite 스냅샷 저장
├── mcp_server.py          # MCP 서버 (Claude Code 연동, 7개 도구)
├── price_alerts.py        # 가격 알림 모니터링 (5분 간격)
├── alert_config.json      # 알림 설정 (종목별 손절선/목표가)
├── portfolio_config.json  # 현금 잔고 / 리스크 프로필
├── technical_analysis.py  # 기술적 분석 (ATR/MA/피보나치/볼린저/RSI/거래량)
├── market_data.py         # 시장 데이터 + 종목 검증 + 종합 점수
├── news_monitor.py        # Tier 1 뉴스 감시 (30분 간격)
├── news_sentiment.py      # 뉴스 센티먼트 v2
├── update_thesis.py       # 투자 테제 관리 (예측 추적/확신도/누적 판단)
├── investment_thesis.json # 누적 투자 테제 (종목별 판단/확신도/정확도)
├── portfolio_tracker.py   # 포트폴리오 성과 추적 (일별 스냅샷/추이)
├── validate_report.py     # 보고서 품질 자동 검증
├── price_verify.py        # 보고서 가격 검증 + 자동 보정
├── realtime_price_tracker.py # 장중 1분 실시간 가격 (cron)
├── telegram_bot.py        # 텔레그램 봇 (/t /p /pf /s /r /a /m /ac /w /v /h)
├── telegram_notify.sh     # 보고서 PDF 변환 + 텔레그램 전송
├── md_to_pdf.py           # Markdown → PDF 변환
├── run_report.sh          # Tier 3 US 보고서 (05:05 KST)
├── run_korea_report.sh    # Tier 3 한국 보고서 (15:40 KST)
├── run_premarket.sh       # Tier 2 장전 브리핑 (21:30 KST)
├── run_midcheck.sh        # Tier 2 장중 체크 (01:00 KST)
├── event_flash.sh         # Tier 2 이벤트 플래시 (트리거)
├── run_update.sh          # 주가 업데이트 래퍼
├── schedule_reports.py    # 경제지표 일정 기반 보고서 스케줄링
├── docs/                  # 분리된 참조 문서
│   ├── report_template_us.md  # US 보고서 템플릿
│   ├── report_template_kr.md  # 한국 보고서 템플릿
│   └── vertical_map.md        # 종목별 버티컬 분석 맵
├── .venv/                 # Python 가상환경
├── data/                  # 런타임 데이터 (git 제외)
│   ├── monitor/           # Tier 1 감시 데이터
│   └── portfolio_history.json
└── 보고서/                  # 일별 투자 전략 보고서 (git 제외)
    ├── YYYY-MM-DD_HHmm.md      # US 보고서
    ├── 한국/YYYY-MM-DD_HHmm.md  # 한국 보고서
    └── 브리핑/                   # 장전/장중 브리핑
```

## 환경 설정

```bash
# Linux (Ubuntu), Python 3.12+, KST timezone
source .venv/bin/activate
.venv/bin/python3 주가_업데이트.py
```

## MCP 서버 (stock-portfolio)

| 도구 | 설명 |
|------|------|
| `get_stock_prices(tickers)` | 쉼표 구분 티커 → 현재가 |
| `get_portfolio()` | 포트폴리오 현황 (현재가/환율) |
| `get_exchange_rates()` | USD/KRW, JPY/KRW, EUR/KRW |
| `get_dividends(tickers)` | 12개월 배당 |
| `run_price_update()` | 주가_업데이트.py 실행 |
| `get_report(date)` | 보고서 읽기 (미입력 시 최신) |
| `record_trade(...)` | SQLite DB에 매수/매도 추가 |

## 스케줄링 (cron)

| Tier | 스크립트 | 시간 (KST) | 모델 | 비용 |
|------|---------|-----------|------|------|
| 1 감시 | `news_monitor.py` | 30분 간격 (시장 시간) | Python | $0 |
| 1 실시간 | `realtime_price_tracker.py` | 매분 (장중) | Python | $0 |
| 2 플래시 | `event_flash.sh` | Tier 1 트리거 | Haiku | $0.3-0.5 |
| 2 장전 | `run_premarket.sh` | 21:30 Mon-Fri | Sonnet | $3-4 |
| 2 장중 | `run_midcheck.sh` | 01:00 Tue-Sat | Sonnet | $3-4 |
| 3 한국 | `run_korea_report.sh` | 15:40 Mon-Fri | Opus | $8-10 |
| 3 US | `run_report.sh` | 05:05 Tue-Sat | Opus | $10-15 |

추가: `portfolio_tracker.py --snapshot` (15:36 KR마감, 05:01 US마감), `price_alerts.py` (5분 간격)
로그: `~/logs/stock-monitor/`

## 가격 알림

- `alert_config.json` — 종목별 손절선/목표가/급등락 임계값
- `price_alerts.py` — 개장 중인 시장만 조회, `.alert_state.json`으로 중복 방지

## 종목 추가/변경 시
1. `portfolio_db.py` SECTOR 딕셔너리에 추가 (전체 스크립트 반영)
2. `add_trade()` 또는 MCP `record_trade()` 매매기록
3. `alert_config.json` 알림 설정
4. `news_monitor.py` TICKER_MARKET, TICKER_NAMES 추가
5. `docs/vertical_map.md` 버티컬 맵 + 이 파일의 보유 종목 테이블 업데이트
6. 검증: `python3 portfolio_db.py --holdings`

---

# 일일 투자 보고서 생성

사용자가 "보고서 만들어줘" 요청 시 아래 절차를 실행한다.

## 1단계: 포트폴리오 현황 + 시장 데이터

```bash
python3 주가_업데이트.py     # 현재가 + 환율 + SQLite 스냅샷
python3 market_data.py      # 시장지수/종목검증/펀더멘탈/수급/종합점수
python3 technical_analysis.py  # ATR/MA/RSI/볼린저/피보나치/거래량/피벗
```

**중요**: 보고서의 모든 가격 기준은 이 실측 데이터 기반. 감이 아닌 수치 근거 명시.
- 손절선 → ATR×2 + 기술적 지지선 클러스터
- 목표가 → 피보나치 확장 + 주요 저항선
- 매수 타점 → 볼린저 하단/과매도/거래량 밀집대
- 숨은진주 발굴 시 반드시 내부자거래/공매도/기관보유율 실데이터 검증

## 2단계: 6개 에이전트 병렬 실행

**반드시 아래 6개 Task를 하나의 메시지에서 동시에 호출한다.**

### Agent 1: 거시경제
```
Task(subagent_type="general-purpose", description="Macro economic research")
prompt:
오늘 날짜: {today}. 보유종목: {tickers}
조사: 경제지표 발표 일정(CPI/PPI/고용/소매판매) + 연준 동향(금리/FOMC/점도표) + 인플레 데이터 + GDP/고용 전망 + 국채 수익률 + 한은/BOJ/ECB. 구체적 수치+날짜. 한국어.
```

### Agent 2: 정치/통상/지정학/부동산
```
Task(subagent_type="general-purpose", description="Politics trade geopolitics")
prompt:
오늘 날짜: {today}
조사: 관세 정책(국별 관세율) + 미중 무역 + 행정명령/규제 + DOGE/셧다운 + 지정학(우크라이나/중동/대만) + 부동산(미국/한국/REITs) + 원자재 슈퍼사이클. 시장 영향 분석. 한국어.
```

### Agent 3: 주식시장/실적
```
Task(subagent_type="general-purpose", description="Stock market earnings news")
prompt:
오늘 날짜: {today}. 보유종목: {tickers}
조사: 실적 발표 예정/결과 + S&P/나스닥/다우 + VIX/풋콜 + 보유종목 뉴스 + IPO + 섹터별 동향. 구체적 수치. 한국어.
```

### Agent 4: 글로벌/환율/원자재
```
Task(subagent_type="general-purpose", description="Global FX commodities crypto")
prompt:
오늘 날짜: {today}
조사: USD/KRW,JPY,EUR + 금/은 + WTI/브렌트/OPEC+ + KOSPI/KOSDAQ + 닛케이/유럽 + BTC/ETH. 구체적 수치. 한국어.
```

### Agent 5: 기관 자금흐름 (역발상)
```
Task(subagent_type="general-purpose", description="Institutional flows contrarian")
prompt:
오늘 날짜: {today}. 보유종목: {tickers}
"뉴스 vs 실제 돈" 차이를 찾아라.
조사: 13F 기관 변동 + 내부자 거래(10b5-1 vs 자발) + 공매도/숏스퀴즈 + 풋콜/이상옵션 + 다크풀 + ETF 흐름(5일/1개월/6개월/1년) + 애널리스트 의심 타이밍 + IB 포지션 vs 리서치 괴리. 한국어.
```

### Agent 6: 숨은 진주 발굴용 데이터
```
Task(subagent_type="general-purpose", description="Hidden gems sector data")
prompt:
오늘 날짜: {today}
수집: 기관 급증(+20%)+주가 미반응 종목 + CEO/CFO 자발적 매수 + 공매도 20%+실적 서프라이즈 + 52주 신저가+기관 매집 + IPO 락업 전 기관 추가매수 + 신규 테마/정책 수혜 비주류 + 한국 외국인+기관 매수/개인 매도. 구체적 티커+수치. 한국어.
```

## 3단계: 보고서 통합 작성

6개 에이전트 결과를 종합하여 `보고서/{today}_{HHmm}.md` 작성.

- **US 보고서 템플릿**: `docs/report_template_us.md` 참조 (Read하여 구조를 따른다)
- **한국 보고서 템플릿**: `docs/report_template_kr.md` 참조
- **종목별 버티컬 분석 맵**: `docs/vertical_map.md` 참조 (공급망/수요처/경쟁사/선행지표)

## 4단계: alert_config.json 업데이트

보고서 완료 후 종목별 가격 기준으로 갱신:
- **stop_loss**: ATR×2 + 기술적 지지 클러스터
- **target**: 피보나치 확장 + 주요 저항선
- **swing_pct**: ATR% × 1.5 (3.0%~7.0%)
- **note**: 핵심 판단 요약, **_updated**: 작성 시각, **_source**: 보고서 파일명
- ETF(429760.KS)는 stop_loss/target = null 유지

## 5단계: 변수 치환

- `{today}`: YYYY-MM-DD
- `{tickers}`: 005930.KS, 000660.KS, 035420.KS, 195940.KQ, 429760.KS, 1377.T, BAYN.DE, BOTZ, CVX, GOOGL, MSFT, NVDA, PLTR, QCOM, SLV, TSLA, UNH, WRB, XOM
- `{총액}`, `{손익}`, `{손익률}`: 주가_업데이트.py 결과
- `{원달러}`, `{원엔}`, `{원유로}`: 환율

---

# 분석 프레임워크

## 종합 점수 체계 (4축 정량 분석)

| 축 | 가중치 | 산출 | 컴포넌트 |
|------|--------|------|----------|
| 기술적 | 35% | technical_analysis.py | RSI/MACD/볼린저/추세/이평선/가격위치 |
| 펀더멘탈 | 30% | market_data.py | 밸류에이션/수익성/성장/재무/성장함정/배당/실적Beat/DCF |
| 수급 | 25% | market_data.py | 기관보유/내부자/공매도/셰이크아웃·분배/거래량 |
| 센티먼트 | 10% | news_sentiment.py | 키워드×소스가중치 + 부정어 + 애널리스트 |

**해석**: +3↑ 강한매수 / +1~+3 매수 / 0~+1 약한매수 / -1~0 약한매도 / -3~-1 매도 / -3↓ 강한매도

**특수 라벨**:
- **셰이크아웃**: 수급 > +2.5 AND 기술적 < 0 → 기관은 매수인데 기술적만 약세 (매수 기회)
- **분배 위험**: 수급 < -2.0 AND 센티 > +1.0 → 뉴스 긍정인데 기관 이탈 (추격 금지)
- **성장함정**: 펀더멘탈에서 성장함정 플래그 발동

## 투자 테제 활용 (Persistent Thesis)

`investment_thesis.json`에 이전 보고서 예측/판단 누적. `update_thesis.py`로 관리.

- **확신도 7+**: 새 근거 없이 판단 변경 금지
- **확신도 3↓**: 예상 범위 넓게, 신중 접근
- **편향 보정**: systematic_bias bullish이면 하향, bearish이면 상향
- **방향성 적중률**: 70%+ 신뢰, 50%↓ 보수적
- worst_tickers → 예측 범위 ATR × 1.5 확대

```bash
python3 update_thesis.py --init          # 초기 빌드
python3 update_thesis.py --summary       # 현재 요약
python3 update_thesis.py --report PATH   # 보고서 후 업데이트
```

## 분석 원칙

### 뉴스 반감기
- **1일 이내**: 소화 중 → 관찰
- **2~3거래일**: 대부분 반영 완료 → "이미 반영"으로 서술
- **1주+**: 완전 소화 → 현재 동인 언급 금지, 배경으로만
- **예외**: 구조적 변화(규제/법/M&A)는 반감기 길지만 가격 반영 여부 확인
- **판별**: 뉴스 후 거래량 스파이크→정상화 = 소화 완료

### 뉴스 신뢰도
- 애널리스트 → 13F 실제 포지션과 대조 (괴리 시 포지션 신뢰)
- 급등락 → 내부자/공매도/풋콜로 실제 방향 확인
- 섹터 로테이션 → ETF 5일/1개월/6개월/1년 전부 확인

### 셰이크아웃 체크리스트
기관 유지/증가? + 내부자 매수? + 공매도 <3%? + 풋콜 <1? + 대형기관 매집?
→ 3개+ Yes = 셰이크아웃 (매도 보류)

### 분배 체크리스트
내부자 매도만? + ETF 1년 유출? + 긍정 뉴스 범람? + 단기만 유입?
→ 3개+ Yes = 분배 (추격 금지)

### 숨은 진주 체크리스트
기관 +20%+주가 미반응? + 내부자 자발적 대규모 매수? + 공매도 20%+실적 서프라이즈? + 정책 수혜+뉴스 미보도? + 외국인+기관 매수/개인 매도?
→ 2개+ Yes = 후보

### 예측 정확도
- 악재 직후 과도한 하방 편향 주의 — 시장 소화 속도 과소평가 금지
- 경제지표 일정 2개+ 공식소스 교차검증
- ETF 흐름 출처+기준일 명시
- 원화 수익 분석 시 환율 변동분 별도 표기
- 예측 회고 최소 1거래일 간격 (같은 날 비교 무의미)

## 핵심 원칙 (매일 리마인드)
1. 뉴스가 아닌 자금흐름을 따르라
2. 기관은 45일 뒤에 공시한다 (13F)
3. 월스트리트 만장일치 = 반대로 가라
4. 이벤트 소화 후 판단
5. 숨은 진주는 데이터에 있다
6. **예측하고 대응하라** — "X가 Y확률로 Z → A를 B에 C한다"
7. 단기(5일)/중기(1~3개월)/장기(6~12개월) 예측+대응 필수
8. **현금은 탄약** — -10% 시 50% 투입, -20% 시 나머지
9. **3분할 매수** — MA20(정찰)/MA50(본격)/MA200(주력)

---

# 종목별 버티컬 분석 맵

→ **`docs/vertical_map.md`** 참조. 보고서 작성 시 Read하여 종목별 공급망/수요처/경쟁사/선행지표를 반영한다.

---

# 한국시장 일일 보고서 생성

→ **`docs/report_template_kr.md`** 참조. `run_korea_report.sh`에 의해 15:40 KST 자동 실행.

### 한국시장 분석 원칙
- 수급: **외국인** > 기관 > 개인. 외국인 연속 일수가 핵심
- 최강 매수 신호: 외국인+기관 순매수 + 개인 순매도
- 코리아 디스카운트: 지배구조, 배당, 정치 리스크, 밸류업
- 특유 이벤트: 선물옵션 만기(둘째주 목), MSCI 리밸런싱(2/5/8/11월), 공매도 정책, 금투세
- 외국인 매수+뉴스 부정 = 셰이크아웃 / 외국인 매도+뉴스 긍정 = 분배

---

# 네이버 API 우선 정책 (2026-04-21 Phase C)

**한국 주식 데이터는 네이버 API를 우선 사용**. 사용자 지시. 기존 yfinance 의존 대폭 축소.

## 래퍼 모듈

| 모듈 | 함수 | 용도 |
|------|------|------|
| `naver_finance.py` | `get_price(ticker)` | 현재가 (한국/미국/일본. 독일은 yf fallback) |
| | `get_ohlcv(ticker, days)` | 일봉 OHLCV. 한국 종목은 **`ForeignPct` 컬럼** 포함 |
| | `get_foreign_retention(ticker, days)` | 외국인 보유율 일별 추이 |
| | `get_kr_investor_flow(ticker, days=3)` | 일별 외인/기관/개인 순매수 + 외인 보유율 변화 |
| | `get_kr_fundamentals(ticker)` | PER/PBR/EPS/BPS/배당/추정PER/52주 |
| | `get_exchange_rate(pair)` | USD/JPY/EUR → KRW 환율 |
| | `get_exchange_history(pair, days)` | 환율 시계열 |
| `naver_broker.py` | `get_brokers(ticker, trader_day=1)` | 거래원 TOP5 (외국계/국내 구분) |

## 사용 규칙

1. **한국 주식**: 무조건 네이버 우선. yfinance는 보완만.
2. **거래원 외국계 판정**: HTML CSS `nv01` + 이름 패턴 (모간/골드만/씨티/UBS/도이치 등 20+) 2중 체크
3. **환율 JPY**: 네이버는 100엔 기준 → 자동 /100 보정됨 (래퍼 내부)
4. **Fallback**: `독일 (BAYN.DE)` 는 네이버 미지원 → yfinance 자동 fallback
5. **상세 가이드**: `docs/naver_api_guide.md` (25개 엔드포인트 전체)
6. **Skill**: `.claude/skills/naver-finance/SKILL.md` (Claude 자동 trigger)

## 보고서 작성 시 적용

- 한국 5종목 (005930/000660/035420/195940/429760) 수급 섹션은 **네이버 실측 데이터로만**
- "외국인 4주 매도" 같은 narrative 표기 → **"외인 -287,316주 3일 / 보유율 -0.08%p"** 정량 표기
- 거래원 외국계 순매수는 `naver_broker` 결과 인용 ("제이피모간 -37,941주")

---

# 페르소나 팀 (2026-04-21)

## 3-tier 구조

```
Tier 1 Core (5명) — 일상 진단 / 의사결정
  민지 (potato-pm) · 현우 (potato-quant) · 지훈 (potato-architect)
  수아 (potato-devil) · 태경 (potato-trader)

Tier 2 Strategy (3명) — 주간 심층 / 매크로/지정학
  재현 (potato-us-politics) · 상훈 (potato-asia-politics) · 도윤 (potato-macro)

Tier 3 Specialists (5명) — 이벤트 트리거 소집
  태주 (potato-trump-mind — 냉정한 트럼프 본인 분석)
  하윤 (potato-trump-clan — 트럼프 가문/측근 네트워크)
  성우 (potato-tech — IT + AI + 반도체/HBM/클라우드/foundation models)
  지원 (potato-frontier — 양자 + 로보틱스 + 차세대 컴퓨팅/핵융합/BCI)
  시우 (potato-scout — 숨은진주 발굴, 체크리스트 기반, 기존 Agent 6 페르소나화)
```

정의 파일: `.claude/agents/potato-*.md` (13개)
매뉴얼: `team/AGENT_TEAMS_MANUAL.md`
메모리: `~/.claude/projects/.../memory/feedback_agent_team_model.md`

## 소집 룰 (태스크별)

| 태스크 | 소집 | 이유 |
|--------|------|------|
| 일상 진단 | Tier 1 (5명) | 의사결정 중심 |
| 주간 심층 | Tier 1 + Tier 2 (8명) | 매크로/정치 해석 |
| 트럼프 관련 이벤트 | T1 + 재현/태주/하윤 | 파벌 + 개인 + 가문 3각 검증 |
| 연준/금리 이벤트 | T1 + 도윤/재현 | 정책 + 경제 |
| AI/반도체/클라우드 | T1 + 성우 | 현 시장 tech 변곡점 |
| 양자/로보틱스/차세대 | T1 + 지원 | frontier tech + BOTZ/Optimus |
| NVDA GTC / Google I/O | T1 + 성우 + 지원 | 현 + 미래 기술 통합 |
| 한국 주식 이슈 | T1 + 상훈 + 현우 | 아시아 정치 + 실측 |
| 숨은진주 발굴 (주간) | T1 + 시우 + 지원 | 스카우트 + frontier 매핑 |
| 13F 공시일 | T1 + 시우 + 태경 | 기관 포지션 + 체크리스트 |
| 11/3 중간선거 | Tier 1+2+3 전원 (13명) | 모든 domain 영향 |

## 활성화 (Agent Teams)

```bash
# 이미 .claude/settings.json 에 활성화됨
# CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
# ~/.claude.json 에 teammateMode: "tmux" (split pane 자동)

# 새 claude 세션에서:
claude
# "potato-pm, potato-quant, ... 5개로 team 만들어" 자연어 지시
```

## 구 tmux harness (deprecated, 참고용)

`team/team-up.sh`, `team/coord-functions.sh` — Agent Teams 발견 전 직접 구현한 것. 사용 금지, 보관용.
정식 경로는 Claude Code Agent Teams 기능 사용.

---

# Round 1/2 진단 결과 (2026-04-21 시스템 자기 진단)

5 페르소나로 시스템 자체 점검한 결과. 추후 보고서 작성 시 맥락으로 활용.

- `team/findings/2026-04-21_round1.md` — 1라운드 (tmux harness)
- `team/findings/round2/SYNTHESIS.md` — 2라운드 종합
- `team/findings/round2/{pm,quant,architect,devil,trader}_*.md` — 페르소나별 산출물

## 핵심 발견 요약

1. **Tier 3 63일 사일런트 다운** (해결완료): crontab CLAUDE 경로 오류 → 2/17~4/21 보고서 미생성. heartbeat 감시 배포.
2. **적중률 수치 자체가 버그** (해결완료): update_thesis.py 소수 누적 → 정수화 fix + --init 재구축
3. **월 비용 $644 실측**: Tier1~3 전부 합산. Alt C (주 1회 Deep Dive 3종목) 파일럿 스크립트 준비됨 (`run_deep_dive_3.sh`)
4. **현금 dry powder 28.2%** (USD $31K + KRW ₩15M): `portfolio_config.json` 에 명시됨. 보고서 헤더에 반드시 분리 표기.
5. **포지션 사이징 vol-target 채택**: Kelly 불가 (적중률 < 50%). NAV × 0.3% = Risk $, Risk/Stop = Size.
