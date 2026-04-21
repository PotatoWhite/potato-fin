---
description: 긴급 브리핑 — 현재 시각 기준 즉시 대응 액션 5개 + Notion 업로드 + Telegram 알림
argument-hint: (선택) 특별히 주목할 이벤트
---

# 긴급 브리핑 생성 (now)

현재 시각 기준 **즉시 대응** 필요한 항목만 뽑아서 간이 브리핑 만든다. 정식 보고서 아니고 **2~3분 빠른 판단**용.

## 실행 순서

1. **실시간 데이터 수집**:
   - `주가_업데이트.py` 실행 (현재가 + 환율)
   - `naver_finance.get_kr_investor_flow()` 한국 5종목 수급 (3일)
   - `naver_broker.get_brokers()` 한국 5종목 거래원 TOP5
   - 최신 보고서 (`ls -t 보고서/*.md | head -1`) 과 비교해서 **변동분만** 추출

2. **손절선 대비 체크**:
   - `alert_config.json` 로드
   - 현재가 vs stop_loss 거리 (위험도 순 5개)
   - 목표가 도달 임박 (+2% 이내) 종목

3. **임박 이벤트 (D-3 이내)**:
   - 오늘/내일/모레 예정 이벤트 (실적/FOMC/관세/지정학)
   - 각 이벤트별 가장 영향 큰 보유 종목 1개

4. **즉시 액션 박스 (우선순위 5개)**:
   태경(potato-trader) 페르소나 포맷:
   ```
   | # | 액션 | 종목 | Risk $ | Stop | Size | 조건 | 근거 |
   ```

5. **페르소나 소집 (필요시)**:
   - 트럼프 이벤트 → 태주(potato-trump-mind) + 재현(potato-us-politics)
   - 기술 이벤트 → 성우(potato-tech) or 지원(potato-frontier)
   - 한국 이슈 → 상훈(potato-asia-politics) + 현우(potato-quant)
   - 매크로 → 도윤(potato-macro)

## 출력

- 파일: `보고서/브리핑/{today}_{HHmm}_brief.md` (200~300줄, 간결)
- 구조:
  1. 헤더 (시각, 총평가, dry powder, 환율)
  2. 🔥 즉시 액션 5개 (우선순위)
  3. 🚨 위험 신호 (손절 근접, 분배 패턴 등)
  4. ⚠ D-3 이벤트 + 포지션 영향
  5. 한 줄 요약

## Notion + Telegram

```bash
bash telegram_notify.sh 보고서/브리핑/{today}_{HHmm}_brief.md "긴급 브리핑"
```

→ `notion_publish.py` 가 Notion DB 업로드 (type: Findings)
→ Telegram 에 Notion 링크 전송

## 제약

- **정식 보고서 아님** — 분석 깊이 제한, 속도 우선
- **Sonnet 권장** (Opus 10~15분 vs Sonnet 2~3분)
- 사용자 입장에서 "지금 뭘 봐야 하나"만 답변
- "지켜봐야 한다", "모니터링" 같은 회피성 표현 금지
- 모든 액션에 구체 수치 (가격/수량/조건)
