---
description: US 정식 일일 투자 보고서 생성 (Opus, 10~15분, 13 페르소나 pool 활용)
---

# US 정식 일일 보고서 생성

cron에서 매일 05:05 KST 자동 실행되는 것과 동일. 수동 실행 시 사용.

## 실행

```bash
cd /home/bravopotato/Spaces/finspace/potato-fin && bash run_report.sh
```

`run_report.sh` 내부 흐름:
1. 주가 업데이트 (`주가_업데이트.py`) — 네이버 우선
2. 기술분석 (`technical_analysis.py`) — 한국은 외국인 보유율 포함
3. 시장 데이터 (`market_data.py`) — 한국 수급 + 거래원 자동 merge
4. Claude CLI (Opus) 호출 — CLAUDE.md 보고서 생성 프로세스 따름
5. 가격 검증 (`price_verify.py --fix`)
6. 투자 테제 업데이트 (`update_thesis.py --report`)
7. 보고서 검증 (`validate_report.py --notify`)
8. 포트폴리오 스냅샷 (`portfolio_tracker.py --snapshot`)
9. 텔레그램 알림 (`telegram_notify.sh`) — **Notion 업로드 + 링크 전송**
9.5. heartbeat 기록
10. 경제지표 스케줄 업데이트

## 보고서 내용 (docs/report_template_us.md 참조)

- 🎯 즉시 액션 박스 (최상단, 태경 포맷)
- 오늘의 핵심 이벤트 (최근 확정 5건 + 향후 2주 8건 + 중기 3건)
- 예측 회고 (직전 보고서 vs 실제)
- **한국 종목 수급 (네이버 실측)** — 외인/기관/개인 + 거래원 외국계 구분
- 보유종목별 분석 (19종목)
- 오늘 1억이 있다면 (자금 배분)
- 2026 연간 로드맵

## 페르소나 활용 (CLAUDE.md "페르소나 팀" 섹션)

보고서 생성 시 Agent Teams 활용 (선택):
- 기본: Tier 1 코어 5명
- 매크로 이벤트 있으면: + 도윤
- 트럼프 관련: + 재현 + 태주 + 하윤
- AI/반도체: + 성우
- 양자/로보틱스: + 지원
- 한국 이슈: + 상훈
- 숨은진주 섹션: + 시우

## 결과

- 파일: `보고서/{today}_{HHmm}.md`
- Notion: fin-invest > 📊 보고서 DB에 자동 업로드 (type: US)
- Telegram: Notion 링크 + 한 줄 요약 메시지
