---
description: 주간/월간 evaluation 실행 — 예측 vs 실제 정산 + 적중률 + 편향 측정
argument-hint: weekly | monthly | quarterly
---

# Evaluation 프로세스

potato-fin 예측 품질을 **정량 측정**. Round 2 현우 지적사항 (적중률 수치 자체가 버그) 해결 후 정기화.

## 실행

```bash
cd /home/bravopotato/Spaces/finspace/potato-fin && bash run_evaluation.sh $ARGUMENTS
```

`$ARGUMENTS`: `weekly` (기본) / `monthly` / `quarterly`

## 평가 대상

| 메트릭 | 계산 | 기준 |
|--------|------|------|
| **방향성 적중률** | `direction_hits / n_predictions × 100` | ≥55% 양호 / 45~55% 동전 / <45% 역지표 |
| **평균 절대 오차율** | `mean(|predicted - actual| / actual × 100)` | <3% 양호 / 3~7% 보통 / >7% 부실 |
| **Signed Bias** | `mean((predicted - actual) / actual × 100)` | \|<2%\| 중립 / >2% bullish / <-2% bearish |
| **PnL 기여도** | 추천 따라갔을 때 vs 인덱스 | S&P 대비 알파 |
| **보고서 생성 성공률** | `보고서 파일 수 / 예상 cron 실행 수` | ≥95% |
| **Tier 3 heartbeat** | 25h+ stale 발생 건수 | 0건 목표 |

## 데이터 소스

- `investment_thesis.json` — 누적 예측 (n_predictions, direction_hits, signed_errors)
- `portfolio.db` — 실제 가격 (snapshots + realtime_prices)
- `data/portfolio_history.json` — 일별 NAV 추이
- `보고서/` — 예측 원본 (회고 대조용)
- `~/logs/stock-monitor/heartbeat.log` — 운영 안정성

## 페르소나 소집

- **현우 (potato-quant)** 주도 — 숫자 측정
- **수아 (potato-devil)** — vanity metric 폭로
- **민지 (potato-pm)** — 이 수치가 사용자 결정에 쓸모 있나
- **지훈 (potato-architect)** — 데이터 무결성 재검사

## 출력

### 주간 (매주 일 21:00 KST 자동)
- 파일: `team/evaluations/weekly_{YYYY-WW}.md` (50~80줄)
- 포함:
  - 지난 주 5일 예측 vs 실제 비교
  - 방향 적중률, 오차율, bias
  - 개선 권고 1~2개
- Notion: type: Findings, 태그 "evaluation-weekly"
- Telegram: 링크 + 한 줄 요약

### 월간 (매월 1일 10:00 KST)
- 파일: `team/evaluations/monthly_{YYYY-MM}.md` (100~150줄)
- 포함:
  - 월간 적중률 + PnL
  - 종목별 breakdown (best/worst 5)
  - S&P500 대비 알파
  - 시스템 변경 추적 (이번 달 개선 사항)
- Notion 업로드

### 분기 (분기 마지막 날)
- 파일: `team/evaluations/quarterly_{YYYY-Q}.md`
- 포함:
  - 분기 PnL + 알파
  - 13F 공시 비교 (우리 예측 vs 기관 실제 포지션)
  - 시스템 ROI 판정 (월 $X 비용 vs 실제 가치)
  - 다음 분기 개선 계획

## 의사 결정 트리거

메트릭 기반 자동 flag:
- 방향 적중률 < 45% 3주 연속 → 시스템 축소 자동 제안 (Alt B/C)
- 오차율 > 10% 월평균 → 예측 레인지 자동 ATR×1.5 확대
- heartbeat stale > 2건/월 → 운영팀 긴급 알림
- NAV vs S&P 알파 < 0 6개월 → 패시브 전환 검토

## Round 2 연장선

Round 2 현우 발견 (n_predictions 소수 버그) 해결 후 재측정. 지금은 clean state (--init 재구축).
4주 후 첫 의미 있는 weekly 가능 (n≥10 종목 확보).
