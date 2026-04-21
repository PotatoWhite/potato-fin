# Round 2 — 태경 (트레이더) 액션 박스 & 포지션 사이징 포맷

> **작성자**: 태경 (potato-trader) · 15년 헤지펀드 시니어 출신
> **대상 보고서**: `보고서/2026-04-21_1954.md` (1062줄, NAV ₩214.5M)
> **문제 의식**: Round 1에서 내가 찍은 7번 문제 — "+3주", "+10주" 추천에 리스크 금액 근거 0. 실제 트레이딩 데스크는 **리스크 $부터 역산해 수량을 뽑는다**. 반대가 아니다.

---

## 진단

보고서가 "무엇을 사는가"는 말하지만 "얼마를 잃을 각오인가"는 말하지 않는다. 이건 **논문**이지 **ticket**이 아니다. 트레이딩 데스크에서 PM에게 올라가는 티켓은 세 줄이다 — `Risk $ / Stop / Size`. 순서도 이 순서다. 사이즈는 **결과**이지 **입력**이 아니다.

- **현재 상태**: 액션 플랜 테이블에 `수량`만 있고 `리스크 금액` 컬럼이 없음 (템플릿 163줄)
- **결과**: PLTR +10주 = 얼마 걸리는가? 손절 $127 기준 현재가 $145 → 주당 $18 × 10주 = $180 (NAV의 0.06%). 리스크가 너무 작으면 **의미 없는 포지션**, 너무 크면 **규율 없는 베팅**. 둘 다 모른다.
- **NAV 대비 single-trade risk 0.2~0.5% 범위 밖으로 나가면 알람**이 떠야 정상이다.

---

## A. 보고서 최상단 "오늘/내일 액션 박스" (마크다운 스니펫)

아래 블록을 `docs/report_template_us.md` 헤더 직후 (예측 기반 대응 원칙 블록 위) 붙여 넣는다. Claude가 보고서 본문 쓰기 전에 **먼저 결정하고 나머지는 근거 채우기** 순서로 강제한다.

```markdown
## 즉시 액션 박스 (Action Box) — 5분 컷

> 이 박스는 **보고서의 결론**이다. 본문은 근거다. 결정을 먼저, 근거는 아래서.
> NAV 기준 단일 트레이드 리스크 **0.2~0.5%** 구간을 벗어나면 `⚠️` 플래그. 벗어난 이유 명시.

**오늘/내일 체결 티켓 (우선순위 순)**

| # | 액션 | 종목 | 리스크 $ | NAV % | 손절폭 | 수량 | 진입 조건 | 근거 (1줄) |
|---|------|------|---------:|------:|-------:|-----:|----------|------------|
| 1 | BUY  | TICKER | $XXX | 0.3% | $Y.YY | N주 | `가격<X or 이벤트Z` | 한 줄 thesis |
| 2 | SELL | TICKER | $XXX | 0.4% | $Y.YY | N주 | `가격>X or 이벤트Z` | 한 줄 thesis |
| 3 | TRIM | TICKER | ―    | ―    | ―     | N주 | 리밸런싱 (25%→20%) | 집중도 초과 |

**오늘 체결 없음 시**:
> `오늘 체결 없음 — 관망. 대기 트리거: (1) XXX 이벤트 / (2) YYY 가격 터치.`
> **관망도 결정이다.** "지켜본다"는 액션이 아니다 — 지켜볼 조건을 숫자로 못 박는다.

**현금 잔고 (Dry Powder)**
- USD dry powder: $XX,XXX (NAV의 X.X%)
- KRW dry powder: ₩X,XXX,XXX (NAV의 X.X%)
- 합계 cash ratio: X.X% (목표 10%, min 5%)
- ⚠️ 통화 불일치 경고: USD 자산 76% vs USD 현금 X% → S&P -10% 시 투입 가능 $?

**오늘의 리스크 예산 (Risk Budget)**
- 총 열린 리스크 (all open stops): $X,XXX (NAV의 X.X%)
- 상한선: NAV의 3% (= $X,XXX). 초과 시 신규 진입 금지.
- 오늘 체결 시 추가 리스크: +$XXX → 합계 X.X%.
```

**포인트**:
- 3줄 이상 넘어가는 순간 읽히지 않는다 → 최대 5티켓 cap
- "관망"도 조건을 수치로 명시 — "시장 불확실"은 금지어
- Risk Budget 합계를 상단에 박음 → PM이 "오늘 얼마 걸렸나" 5초 확인

---

## B. 액션 테이블 포맷 + 공식 유도

### B-1. 공식 체계 (top-down)

```
NAV                        = 총 평가금액 (보고서 헤더)
Single-Trade Risk %        = 0.2% ~ 0.5% (NAV 대비)  ← 이것이 입력값
Risk $                     = NAV × Risk %
Stop Distance $            = |Entry - Stop Loss|
Position Size (shares)     = Risk $ / Stop Distance $
Notional $                 = Size × Entry Price
Notional % of NAV          = Notional $ / NAV        ← 집중도 체크
```

**역순(실무 순서)로 읽으면**:
1. 얼마 잃을 각오? → `Risk $` 결정 (NAV 0.3%)
2. 손절 어디? → `Stop` 결정 (ATR×2 vs 기술적 지지선 중 **더 타이트한 것**)
3. 수량 = Risk ÷ Stop distance
4. Notional 합계가 NAV의 25% 넘으면 **풀 사이즈 금지** (집중도 초과)

### B-2. 왜 0.2~0.5% 인가 (근거)

- **Van Tharp / Market Wizards 공통 규칙**: 개별 트레이드 per-risk 0.5%~2% 상한. 19종목 분산 포트폴리오는 **하한선 0.2%**.
- **Kelly 변형 (half-Kelly)**: 이 시스템 적중률 29.4% (Round 1) → Full Kelly = 음수 (걸면 안 됨). Half-Kelly도 음수. 따라서 **Kelly 채택 불가**, **vol-target 방식** 선택.
- **Vol-target**: NAV 일일 변동성 1% 목표 → 19종목 평균 상관 0.3 가정 시 종목당 ATR 리스크 ≈ NAV 0.2~0.3%가 수학적으로 맞음.
- **선택**: **Vol-target (fixed fractional)**. 적중률이 50% 넘기 전까지는 Kelly 쓰지 마라.

### B-3. 손절폭 결정 — ATR×2 vs 기술적 지지선

| 상황 | 선택 | 이유 |
|------|------|------|
| ATR×2 < 최근 지지선 | **ATR×2 사용** | 지지선 돌파 전에 이미 ATR×2 이탈 → 더 타이트한 쪽이 자본 효율 ↑ |
| ATR×2 > 최근 지지선 | **지지선 사용** | 지지선 위에서 꿇는 건 "노이즈". 더 타이트한 쪽. |
| 지지선 불명확 (저점 갱신 중) | **ATR×2만 사용** | Falling knife — "Don't catch a falling knife" |
| 대형주 GOOGL/MSFT | ATR×2 + MA50 중 큰 쪽 | 대형주는 노이즈가 큼. 타이트하면 털림 |

**원칙**: 더 **타이트한 쪽** 기본. 단 falling knife 는 ATR만.

---

## C. 실제 예시 2개 (현재 보유 종목 시연)

### 예시 1: UNH 실적 대비 매수 티켓

**컨텍스트** (`alert_config.json` + 보고서):
- 현재가 $323.48, 손절 $300, 목표 $350
- 4/21 장후 Q1 실적. Miss(15%) 시나리오 시 $295 분할매수 대기
- NAV = ₩214,509,709 ≈ $146,040 (USD/KRW 1,468.84 기준)

**Miss 시나리오 실행 (ticket)**:

```
Risk %        = 0.3%  (NAV 대비; UNH는 보유 중 평균 단가 플러스 상태 → 추가 매수 리스크 완화)
Risk $        = $146,040 × 0.003 = $438
Entry         = $295 (Miss 시 gap-down 예상 타점)
Stop          = $280 (ATR×2=$15 + MA200 $282 클러스터 → 더 타이트한 $280)
Stop Distance = $15
Size          = $438 / $15 = 29주
Notional      = 29 × $295 = $8,555 (NAV의 5.86%)
```

**검증**:
- Notional 5.86% → 기존 UNH 비중에 더해 체크. 합산 10% 이하면 OK.
- Beat(55%) 시나리오: **신규 매수 없음**. "Beat는 추격 금지" = 액션 플랜에 `—` 남김.

**액션 박스 행**:
```
| 1 | BUY | UNH | $438 | 0.3% | $15 | 29주 | $295 이하 (Miss 시) | DOJ 해소 + 내부자 +$3M, MLR 악화 한정 매수 |
```

### 예시 2: GOOGL 리밸런싱 (24.9% → 20% 축소)

**컨텍스트**:
- 현재 비중 24.9% (NAV ₩214.5M 기준 GOOGL 평가액 ≈ ₩53.4M ≈ $36,360)
- 목표 비중 20% (`portfolio_config.json: max_single_stock_pct=20`)
- 현재가 $337.42

**계산**:

```
현재 GOOGL Notional    = NAV × 24.9%  = $36,364
목표 GOOGL Notional    = NAV × 20.0%  = $29,208
매도 Notional          = $36,364 - $29,208 = $7,156
매도 수량              = $7,156 / $337.42 = 21주
```

**매도 분할 (실무)**:
- GOOGL 4/24 실적 전 **선제 10주 매도** (리스크 감축)
- 실적 Beat → $355 도달 시 **추가 11주 매도** (목표 달성 이익실현)
- 실적 Miss → $320 터치 시 **추가 매도 보류** (손실 중 매도는 "forced selling")

**액션 박스 행**:
```
| 3 | TRIM | GOOGL | — | — | — | 10주 | 4/24 실적 전 선제 | 집중도 24.9%→23% (단일 종목 상한 20%) |
| 4 | TRIM | GOOGL | — | — | — | 11주 | $355 도달 시 (Beat 후) | 목표가 도달 + 비중 20% 달성 |
```

**Note**: 리밸런싱 매도는 리스크 $ 아닌 **비중 공식**으로 돌아감. 컬럼에 `—` 표시 OK.

---

## D. `alert_config.json` 확장 제안 (리밸런싱 룰 자동 트리거)

### D-1. 신규 top-level 필드

```json
{
  "markets": { ... },
  "rebalancing_rules": {
    "max_single_weight": 0.20,
    "max_sector_weight": 0.40,
    "max_correlation_cluster": 0.55,
    "_cluster_definitions": {
      "mega_cap_tech": ["GOOGL", "MSFT", "NVDA", "PLTR"],
      "energy": ["CVX", "XOM"],
      "kr_semi": ["005930.KS", "000660.KS"]
    },
    "min_cash_pct_usd": 0.05,
    "min_cash_pct_total": 0.10,
    "single_trade_risk_pct": 0.003,
    "single_trade_risk_max": 0.005,
    "total_open_risk_cap_pct": 0.03,
    "_notes": "max_single_weight 초과 시 자동 TRIM 알림. total_open_risk 3% 초과 시 신규 진입 거부."
  },
  "alerts": { ... }
}
```

### D-2. 트리거 동작 (`price_alerts.py` 확장안)

```python
# 의사코드 — 실제 구현은 지훈에게
def check_rebalance_triggers(portfolio, config):
    rules = config["rebalancing_rules"]
    alerts = []

    # 1. 단일 종목 비중 초과
    for ticker, pos in portfolio.items():
        if pos.weight > rules["max_single_weight"]:
            excess_usd = (pos.weight - rules["max_single_weight"]) * portfolio.nav
            shares_to_sell = int(excess_usd / pos.current_price)
            alerts.append(
                f"⚠️ REBAL: {ticker} {pos.weight:.1%} > {rules['max_single_weight']:.0%} "
                f"→ {shares_to_sell}주 매도 제안 (Notional ${excess_usd:,.0f})"
            )

    # 2. 클러스터 비중
    for cluster_name, tickers in rules["_cluster_definitions"].items():
        cluster_weight = sum(portfolio[t].weight for t in tickers if t in portfolio)
        if cluster_weight > rules["max_correlation_cluster"]:
            alerts.append(
                f"⚠️ CLUSTER: {cluster_name} {cluster_weight:.1%} > {rules['max_correlation_cluster']:.0%}"
            )

    # 3. USD 현금 부족
    usd_cash_pct = portfolio.usd_cash / portfolio.nav
    if usd_cash_pct < rules["min_cash_pct_usd"]:
        alerts.append(
            f"⚠️ DRY POWDER: USD {usd_cash_pct:.1%} < {rules['min_cash_pct_usd']:.0%} "
            f"→ S&P -10% 시 분할매수 탄약 부족"
        )

    return alerts
```

**중요**: 알림은 **제안**만 — 실제 매매는 사용자 승인 후. 자동 매도 금지 (pump/dump 보호).

---

## E. `portfolio_config.json` 확장 제안 (통화별 cash 분리 + 리스크 프로필 명시화)

### E-1. 현재 문제

```json
// 현재
{
  "cash": { "USD": 45624.13, "KRW": 0, "JPY": 0, "EUR": 0 },
  "risk_profile": {
    "max_single_stock_pct": 20,
    "max_sector_pct": 40,
    "min_cash_pct": 5,
    "target_cash_pct": 10
  }
}
```

**문제**:
1. 보고서 헤더의 "현금 탄약 21.6%"는 **원화 통화 비중** — cash가 아님. (Round 1 태경 발견)
2. `min_cash_pct` 5%가 USD 기준인지 total 기준인지 불명
3. `single_trade_risk_pct` 필드 없음 → 보고서가 매번 다른 사이즈 추천

### E-2. 확장안

```json
{
  "cash": {
    "USD": 45624.13,
    "KRW": 0,
    "JPY": 0,
    "EUR": 0
  },
  "currency_exposure": {
    "_note": "자산 통화 비중 (portfolio_tracker.py 계산값) — cash와 별개",
    "USD_asset_pct": 0.765,
    "KRW_asset_pct": 0.216,
    "JPY_asset_pct": 0.018,
    "EUR_asset_pct": 0.001
  },
  "dry_powder": {
    "_note": "실제 투입 가능한 현금. 보고서 헤더에 이 값을 표시.",
    "USD_cash_pct_of_nav": 0.00,
    "KRW_cash_pct_of_nav": 0.00,
    "total_cash_pct_of_nav": 0.00,
    "_auto_computed": true
  },
  "crypto": {
    "BTC": { "amount_krw": 5000000 },
    "ETH": { "amount_krw": 5000000 }
  },
  "risk_profile": {
    "max_single_stock_pct": 0.20,
    "max_sector_pct": 0.40,
    "max_correlation_cluster_pct": 0.55,
    "min_cash_pct_usd": 0.05,
    "min_cash_pct_total": 0.10,
    "target_cash_pct_total": 0.15,
    "single_trade_risk_pct": 0.003,
    "single_trade_risk_max_pct": 0.005,
    "total_open_risk_cap_pct": 0.03,
    "position_sizing_method": "vol_target",
    "_position_sizing_rationale": "적중률 29.4% → Kelly 불가. Vol-target(fixed fractional) 채택. 적중률 55%+ 달성 시 half-Kelly 재검토.",
    "daily_vol_target_pct": 0.01,
    "stop_loss_method": "tighter_of_ATRx2_and_support",
    "_updated_rationale": "Round 1/2 태경 권고 반영. min_cash_pct_usd 분리, single_trade_risk_pct 명시."
  },
  "cash_deploy_rules": {
    "trigger_1": { "condition": "S&P500 고점 대비 -10%", "action": "USD cash의 50% 투입", "target": "MA50 터치 + 종합점수 상위" },
    "trigger_2": { "condition": "S&P500 고점 대비 -20%", "action": "USD cash 전량 (min_cash_pct_usd 5% 유지)", "target": "MA200 터치 + 펀더 건전" },
    "_warning": "KRW cash 0원이면 한국 종목 급락 시 분할매수 불가. 월 ₩500K 이상 KRW 축적 권장."
  }
}
```

**핵심 변경점**:
- `currency_exposure` 신규 (자산 통화 비중, 혼동 제거)
- `dry_powder` 신규 (실제 현금, NAV 대비 %)
- `risk_profile`에 `single_trade_risk_pct`, `stop_loss_method`, `position_sizing_method` 명시
- `min_cash_pct_usd` vs `min_cash_pct_total` 분리 — USD 자산 76%인데 USD cash 0% 상태 차단

---

## F. 페르소나 형식 결산

### 진단

1. **보고서는 에세이, 트레이더는 티켓이 필요하다** — 1062줄 중 "사이즈가 왜 그 사이즈인가" 설명 0줄. Risk $ 컬럼 신설이 가장 싼 수정.
2. **적중률 29.4%에 Kelly 쓰면 계좌 녹는다** — Vol-target 채택 명시하고 미신 끊어야 한다.
3. **현금 21.6%는 통화 비중이지 dry powder가 아니다** — Round 1에서 찍었고, `portfolio_config.json` 필드 분리로 해결.

### 우려

- **GOOGL 24.9%** — 4/24 실적 Miss 시 -5% 가정해도 NAV -1.24% 단일 종목 원샷. 사전 10주 트림 안 하면 "왜 안 팔았어?"라는 자책이 기다린다. "let winners run"은 **리스크 제한된 winner**에만 해당. 비중 초과 winner 는 **분배 후보**다.
- **CVX + XOM** — 4/22 이란 휴전 만료 재격발 시 둘 다 +6% 같은 방향. 에너지 클러스터 비중 체크 없으면 "한 이벤트에 두 포지션"이 성립. 나쁘지 않지만 **의도한 것인가 우연인가** 명시 필요.
- **PLTR $10주 추가매수 권고** — 현재가 $145 기준 손절 $127 = $18/주, 10주면 리스크 $180 (NAV 0.12%). **너무 작다**. 이 사이즈로는 맞아도 NAV에 티가 안 난다. 진짜 확신이면 0.4% 리스크 = 약 33주 가야 한다. **어정쩡한 사이즈는 확신 부족의 신호**.

### 제안

**가장 싼 변경 1개**: `docs/report_template_us.md` 헤더 바로 밑에 **액션 박스 템플릿 (섹션 A)** 강제 삽입 + `portfolio_config.json`에 `single_trade_risk_pct: 0.003` 필드 추가. 이 둘만 있으면 Claude가 보고서 쓸 때 **Risk $ → Stop → Size 순서**로 계산하게 되고, "+10주" 같은 허수 추천이 사라진다.

코드 변경은 30줄 이내 (`portfolio_tracker.py`의 NAV 읽어서 risk_pct 곱하는 공식만 추가). 지훈에게 넘긴다.

### 한 줄 요약

이 보고서는 **시나리오 상상력 있는 애널리스트**에게는 **훌륭한 교재**지만, **실제 리스크 버짓을 지켜야 하는 트레이더**에게는 **사이즈 규율이 비어있는 목표가 콜렉션**에 약하다.

---

## 부록: 구현 순서 (지훈에게 넘기는 TO-DO)

1. `portfolio_config.json` 스키마 확장 (Section E) — 5분
2. `docs/report_template_us.md` 헤더 직후 액션 박스 템플릿 삽입 (Section A) — 5분
3. `docs/report_template_kr.md` 동일 적용 — 5분
4. `alert_config.json` 에 `rebalancing_rules` top-level 추가 (Section D-1) — 5분
5. `price_alerts.py` 에 `check_rebalance_triggers()` 추가 (Section D-2 의사코드) — 30분
6. `portfolio_tracker.py` 에 dry_powder 계산 + `portfolio_config.json` 자동 업데이트 — 20분
7. 다음 보고서 생성 시 Claude 에이전트에 "액션 박스 섹션 스킵 금지, Risk $ 필수 계산" 시스템 프롬프트 주입 — 민지(PM)와 협의

합계 70분 작업. 월 $300 모델 비용 줄이는 것보다 **이게 먼저**다. 작게 새는 배는 큰 배보다 빨리 가라앉는다.
