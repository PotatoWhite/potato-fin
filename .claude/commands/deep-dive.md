---
description: Deep Dive 3 — 매주 금 17:00 자동 실행. 3종목만 집중 분석 (Alt C 체제, 월 $36 비용)
---

# Deep Dive 3 실행

Round 2 수아 권고 Alt C 체제. 19종목 전수 조사 대신 **가장 중요한 3종목만 깊게**.

## 3종목 선정 로직

`run_deep_dive_3.sh` 내부 Python:
1. **최대 비중 종목** (`portfolio.db` 에서 평가금액 1위) — 현재 GOOGL 24.9%
2. **최악 bias 종목** (`investment_thesis.json` `bias_tracker.avg_error_pct` 최대 절대값)
3. **최근 7일 최대 변동 종목** (`realtime_prices` 테이블에서 range/avg)

## 분석 구조 (각 종목당)

5 페르소나 순차 분석:
- **민지 (PM)**: 이 종목으로 사용자가 오늘 어떤 결정?
- **현우 (퀀트)**: thesis.json의 n_predictions/bias 실측
- **지훈 (아키텍트)**: alert_config 구멍 1개
- **태경 (트레이더)**: 액션 티켓 1장 (Risk$/Stop/Size 필수)
- **수아 (악마)**: 보유 정당성 공격 + 대안

## 실행

```bash
cd /home/bravopotato/Spaces/finspace/potato-fin && bash run_deep_dive_3.sh
```

자동 cron: **매주 금요일 17:00 KST** (KR 장 마감 직후)

## 비용 비교

| 체제 | 월 비용 | 산출물 |
|------|--------|--------|
| 기존 (일일 Opus 19종목) | **$644** | 1062줄 매일, 아마 안 읽음 |
| **Alt C (Deep Dive 3)** | **$36** (94% 절감) | 150줄/주 × 3종목 깊이 |

절감분 $608/월 → SPY 적립 가능 (연 $7,296).

## 결과

- 파일: `보고서/deep_dive_3/{today}_{HHmm}.md` (최대 150줄)
- Notion: type: DeepDive
- Telegram: Notion 링크
