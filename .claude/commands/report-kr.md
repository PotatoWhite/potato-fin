---
description: 한국 정식 일일 투자 보고서 생성 (Opus, 장 마감 후 15:40 KST 자동 실행분 수동 호출)
---

# 한국시장 일일 보고서 생성

```bash
cd /home/bravopotato/Spaces/finspace/potato-fin && bash run_korea_report.sh
```

`run_korea_report.sh` 내부:
1. 주가 업데이트 — **네이버 우선** (한국 정확도 높음)
2. 시장 데이터 + 기술분석
3. Claude Opus 호출 — `docs/report_template_kr.md` 템플릿 따름
4. 가격 검증, 테제 업데이트, 스냅샷
5. `telegram_notify.sh` → Notion + Telegram

## 한국 보고서 특화 (네이버 실측 기반)

- `naver_finance.get_kr_investor_flow()` — 3일 외인/기관/개인 순매수
- `naver_finance.get_kr_fundamentals()` — PER/PBR/EPS/BPS/배당/외인소진율
- `naver_broker.get_brokers()` — 거래원 TOP5 (외국계/국내 구분)
- `naver_finance.get_foreign_retention()` — 외국인 보유율 추이

## 페르소나 활용

- **상훈** (potato-asia-politics): 중국/한국/일본 정치 + 금투세/밸류업
- **현우** (potato-quant): 한국 수급 수치 검증
- **시우** (potato-scout): 한국 외국인+기관 매수 + 개인 매도 종목 발굴

## 보유 한국 5종목

| 티커 | 종목 |
|------|------|
| 005930.KS | 삼성전자 |
| 000660.KS | SK하이닉스 |
| 035420.KS | NAVER (5월까지 매도 금지) |
| 195940.KQ | HK이노엔 |
| 429760.KS | PLUS 미국S&P500 ETF |

## 결과

- 파일: `보고서/한국/{today}_{HHmm}.md`
- Notion: type: KR
- Telegram: Notion 링크
