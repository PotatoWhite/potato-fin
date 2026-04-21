# Notion 자동 발행 설정 가이드 (5분)

potato-fin 의 모든 보고서가 cron 에서 자동으로 Notion DB 에 업로드되고 Telegram 으로 링크가 전송되도록 설정.

## 1. Integration 생성 (2분)

1. https://www.notion.so/my-integrations 접속
2. **New integration** 클릭
3. 설정:
   - Name: `potato-fin-reports`
   - Associated workspace: 본인 워크스페이스
   - Type: **Internal**
4. **Submit** → 생성됨
5. **Internal Integration Secret** 복사 (`ntn_` 로 시작)

## 2. DB에 Integration 연결 (1분)

1. 이미 만든 보고서 DB 열기: https://www.notion.so/b63e9e1bfca34492bbda0268ef2eb599
2. 우측 상단 `⋯` (점 3개) 메뉴 클릭
3. **Connections** 선택
4. `potato-fin-reports` 검색 → 선택 → **Confirm**
5. ✅ DB가 Integration에 공유됨

## 3. .env 에 값 저장 (1분)

```bash
cd /home/bravopotato/Spaces/finspace/potato-fin

# .env 파일 확인 (이미 있으면 Telegram 값 유지)
ls -la .env

# NOTION 두 줄 추가 (또는 기존 편집)
echo "" >> .env
echo "NOTION_TOKEN=ntn_여기에_복사한_secret" >> .env
echo "NOTION_DATABASE_ID=b63e9e1b-fca3-4492-bbda-0268ef2eb599" >> .env

# 검증
grep NOTION .env
```

## 4. 수동 테스트 (1분)

```bash
cd /home/bravopotato/Spaces/finspace/potato-fin

# 최근 보고서 파일로 테스트 업로드
.venv/bin/python3 notion_publish.py 보고서/2026-04-21_1954.md US --summary "Notion 테스트"

# 결과: https://www.notion.so/xxx 형태 URL 출력되면 성공
```

## 5. 자동 파이프라인 확인

한 번 테스트 성공하면 **모든 cron 보고서가 자동으로 Notion 업로드**:

| Cron 실행 | 스크립트 | Notion type | Telegram |
|----------|---------|-------------|----------|
| 05:05 화~토 | run_report.sh | US | 링크 전송 |
| 15:40 월~금 | run_korea_report.sh | KR | 링크 전송 |
| 21:30 월~금 | run_premarket.sh | Premarket | 링크 전송 |
| 01:00 화~토 | run_midcheck.sh | Midcheck | 링크 전송 |
| 17:00 금 | run_deep_dive_3.sh | DeepDive | 링크 전송 |
| 16:00 금 | run_scout_weekly.sh | Findings | 링크 전송 |
| 21:00 일 | run_evaluation.sh weekly | Findings | 링크 전송 |
| 10:00 매월1 | run_evaluation.sh monthly | Findings | 링크 전송 |
| 이벤트 트리거 | event_flash.sh | Findings | 링크 전송 |

## 실패 시 fallback

`notion_publish.py` 는 **non-fatal** — NOTION_TOKEN 없거나 API 실패 시:
- 에러 로그만 남기고 exit 0
- Telegram 은 MD 파일 직접 첨부로 전송 (fallback)

즉 Notion 설정 안 해도 기존 Telegram 알림은 계속 작동.

## Notion API 제한

- Rate limit: ~3 req/sec (per integration)
- Page content: ~100 blocks per request (자동 분할됨)
- MD → Notion 변환: code block 위주로 간소화 (markdown 유지)

## 문제 해결

| 에러 | 원인 | 해결 |
|------|------|------|
| 401 Unauthorized | Token 오류 | .env 의 NOTION_TOKEN 재확인 |
| 404 Not Found | DB ID 오류 or integration 미연결 | Connections 다시 확인 |
| 403 Forbidden | DB 권한 없음 | Connections 에 integration 추가 |

## 참고

- `.env.example` — 템플릿
- `notion_publish.py` — 구현
- `telegram_notify.sh` — 호출부
