---
description: 시스템 자가 진단 — 13 페르소나 팀 소집해서 potato-fin 자체를 평가
argument-hint: 진단 대상 (예: "오늘 US 보고서" / "update_thesis.py 버그" / "전체 시스템")
---

# 시스템 자가 진단 (페르소나 팀)

potato-fin 시스템 자체를 페르소나 팀으로 진단. Round 1/2 패턴의 후속.

## 실행 옵션

### 옵션 A — 정식 Agent Teams (새 claude 세션)
```bash
# 새 터미널에서
cd /home/bravopotato/Spaces/finspace/potato-fin
tmux new-session -A -s potato 'claude'

# claude 세션 안에서:
potato-pm, potato-quant, potato-architect, potato-devil, potato-trader
5개 subagent로 team 만들어. 진단 대상: $ARGUMENTS
각자 페르소나 관점에서 진단/우려/제안/한 줄 요약 작성 후 종합.
```

### 옵션 B — 현재 세션에서 병렬 Agent spawn
이 세션에서 Agent tool로 5~7 페르소나 병렬 spawn (general-purpose 로 persona 내용 embedding).
결과는 `team/findings/round{N}/` 에 저장.

## 진단 결과 저장

- 개별: `team/findings/round{N}/{persona}_*.md`
- 종합: `team/findings/round{N}/SYNTHESIS.md`
- Notion: type: Round1/Round2/Round3 등

## 페르소나 소집 (진단 대상별)

| 대상 | 기본 5 | 추가 |
|------|-------|-----|
| 전체 시스템 | 코어 5 | - |
| 보고서 품질 | 코어 5 | 도윤 + 상훈 |
| 예측 정확도 | 코어 5 | 현우 특별 주도 |
| 비용/가치 | 코어 5 | 수아 특별 주도 |
| 페르소나 구조 | 코어 5 | - |
| 기술 커버리지 | 코어 5 | 성우 + 지원 |
| 숨은진주 발굴력 | 코어 5 | 시우 |

## Round 1/2 핵심 발견 참조

- `team/findings/2026-04-21_round1.md` — tmux harness, 63일 사일런트 다운 등
- `team/findings/round2/SYNTHESIS.md` — 적중률 버그, $644 실측, 5 deliverable

Round 3+ 은 여기 이어서.

## 제약

- 이 세션은 `.claude/agents/` 로드 전 시작된 경우 potato-* subagent 직접 spawn 불가
- 그럴 땐 general-purpose 로 persona 내용 embedding
- 정식 Agent Teams는 새 세션에서만 split pane 작동
