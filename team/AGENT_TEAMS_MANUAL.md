# Claude Code Agent Teams — 사용 매뉴얼

> 출처: <https://code.claude.com/docs/en/agent-teams.md> · 작성: 2026-04-21
> 적용 환경: Claude Code v2.1.116, tmux 3.4, Linux/zsh

## 0. 한 줄 요약

여러 Claude Code 인스턴스를 **하나의 팀**으로 묶어, 같은 task list와 mailbox를 공유하면서 병렬로 일하게 만드는 공식 기능. **실험적**(experimental).

핵심 차이점 — **Subagent vs Agent Team**:
| 구분 | Subagent | Agent Team |
|------|----------|-----------|
| 동작 | 한 세션 내에서 잠깐 호출 → 결과 반환 | 별도 세션, 영구 컨텍스트 유지 |
| 통신 | main agent에게만 보고 | **teammate끼리 직접 message** |
| 용도 | 한 번 쓰고 버리는 작업 | 여러 라운드 토론·협업 |
| 토큰 비용 | 낮음 (요약만 main에 들어옴) | 높음 (각자 풀 컨텍스트) |

→ "5명이 같은 보고서를 찢는다" 같은 다관점 진단 = **Agent Teams**

---

## 1. 사전 요구사항

| 항목 | 우리 환경 | 비고 |
|------|----------|------|
| Claude Code | v2.1.32+ | 우리: **2.1.116 ✅** |
| tmux (split panes 모드) | 필요 | 우리: **3.4 ✅** |
| 또는 iTerm2 + `it2` CLI | macOS만 | 우리는 tmux로 OK |
| Linux 터미널 | OK | VS Code/Windows Terminal/Ghostty는 split-pane 미지원 |

```bash
claude --version  # 2.1.32 이상 확인
which tmux         # tmux 설치 확인
```

---

## 2. 활성화 (한 번만)

Agent Teams는 **기본 비활성**. 환경변수 또는 settings.json으로 켠다.

### 방법 A — 프로젝트 settings.json (추천, git에 들어감)

`.claude/settings.json` 생성/편집:
```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

### 방법 B — 사용자 settings.json (모든 프로젝트에 적용)

`~/.claude/settings.json`:
```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

### 방법 C — shell env (빠른 테스트)

```bash
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
claude
```

### 디스플레이 모드 (선택)

`~/.claude.json`에 추가하면 split-pane 모드 강제:
```json
{
  "teammateMode": "tmux"
}
```

값:
- `auto` (기본) — tmux 안에서 시작하면 split-pane, 아니면 in-process
- `tmux` — split-pane 강제 (tmux/iTerm2 자동 감지)
- `in-process` — 단일 터미널, Shift+Down으로 teammate 순환

세션 단위 override:
```bash
claude --teammate-mode in-process
```

---

## 3. Teammate 정의 (subagent 재사용)

각 페르소나를 `.claude/agents/{name}.md` 또는 `~/.claude/agents/{name}.md`에 정의.

**우리 프로젝트 예시** (`.claude/agents/potato-pm.md`):
```markdown
---
name: potato-pm
description: potato-fin의 제품책임자 페르소나 "민지". 사용자 의사결정 관점에서 평가.
model: opus
color: green
---

너는 potato-fin 프로젝트의 PM **민지**다. ...
```

### Frontmatter 필드

| 필드 | 필수 | 설명 |
|------|------|------|
| `name` | ✅ | 소문자+하이픈 ID (e.g. `potato-pm`) |
| `description` | ✅ | 언제 이 agent에 위임할지 (lead가 의사결정에 사용) |
| `model` | | `opus`, `sonnet`, `haiku`, 풀명(`claude-opus-4-7`), 또는 `inherit` |
| `tools` | | 허용 툴 allowlist (생략 시 main 세션 모두 상속) |
| `disallowedTools` | | 차단할 툴 |
| `color` | | `red`/`blue`/`green`/`yellow`/`purple`/`orange`/`pink`/`cyan` (UI 식별용) |
| `permissionMode` | | `default`/`acceptEdits`/`auto`/`dontAsk`/`bypassPermissions`/`plan` |
| `effort` | | `low`/`medium`/`high`/`xhigh`/`max` (모델별 가능 레벨 다름) |
| `maxTurns` | | agentic turn 상한 |
| `skills` | | 사전 로드할 skill 리스트 (주의: agent team 모드에선 무시될 수 있음) |
| `mcpServers` | | 사전 로드할 MCP 서버 (주의: agent team 모드에선 무시될 수 있음) |
| `memory` | | `user`/`project`/`local` — 세션 간 학습 누적 |

⚠ **중요**: agent team으로 spawn될 때 body는 **default system prompt에 append** 된다 (replace 아님). 그래서 본문에 "너는 Claude Code다" 같은 문구 쓸 필요 없음.

### Scope 우선순위

| 위치 | 범위 | 우선순위 |
|------|------|----------|
| Managed settings | 조직 | 1 (최고) |
| `--agents` CLI 플래그 | 현재 세션만 | 2 |
| `.claude/agents/` | 현재 프로젝트 | 3 |
| `~/.claude/agents/` | 모든 프로젝트 | 4 |
| Plugin agents | plugin 활성 시 | 5 (최저) |

### 변경 후 반영

```bash
# subagent 파일 추가/수정 후 → 새 claude 세션 시작 필요
# 또는 실행 중 세션 안에서:
> /agents
```

---

## 4. 팀 시작하기

```bash
cd /home/bravopotato/Spaces/finspace/potato-fin
claude  # 이 세션이 lead가 됨
```

세션 안에서 자연어로 요청:

```
potato-pm, potato-quant, potato-architect, potato-devil, potato-trader
이 5개 subagent로 agent team을 만들어. 각 페르소나 정의에 따라 역할 분담.
```

또는 task 같이 넘기기:
```
보고서/2026-04-21_1954.md 를 5명이 동시에 찢어. 페르소나 정의에 따라
진단/우려/제안/한 줄 요약 4섹션. 끝나면 너가 종합.
```

Lead Claude가:
1. 5 teammate spawn
2. 공유 task list 생성
3. broadcast/message로 작업 분배
4. 각자 끝나면 자동 idle notification 받음
5. 합의/종합 후 너에게 보고

---

## 5. 작동 중 제어

### 자연어로 lead에게 명령

```
태경(potato-trader)에게 추가로 물어봐: "현금 0% 시나리오에서 GOOGL을 어떻게 헤지?"
```

```
모든 teammate에게 broadcast: "alert_config.json을 ATR×2.5로 갱신할 때 영향 분석"
```

```
지훈(potato-architect)이 끝낼 때까지 기다린 다음 그 결과를 현우(potato-quant)에게 전달.
```

### 수동 제어 (in-process 모드)

| 키 | 동작 |
|----|------|
| `Shift+Down` | teammate 순환 (마지막 → lead로 wrap) |
| `Enter` | 선택한 teammate 세션 보기 |
| `Esc` | teammate의 현재 turn 중단 |
| `Ctrl+T` | task list 토글 |

### Split-pane 모드 (tmux)

각 teammate가 별도 pane → 클릭/키로 직접 진입.

```bash
tmux ls  # 자동 생성된 세션 확인
```

### 모델/사이즈 명시

```
4명 teammate로 만들어. 모두 Sonnet 사용.
```

```
보안 검토 teammate 1명 spawn. plan approval 필수로 — 코드 변경 전에 내가 승인.
```

---

## 6. Plan approval 모드

risky한 task는 teammate가 plan-mode (read-only)로 시작 → lead가 approve해야 진행.

```
auth 모듈 리팩토링할 architect teammate spawn.
plan approval 필수. test coverage 없는 plan은 reject 기준.
```

Lead가 자동 판단. Reject되면 teammate가 plan 수정 → 재제출.

---

## 7. Task list

공유 작업 큐. 상태: `pending` → `in_progress` → `completed`. 의존성 가능.

- **Lead 할당**: "task #3을 현우에게 줘"
- **Self-claim**: teammate가 끝나면 다음 unassigned task 알아서 픽
- File locking으로 race condition 방지

```
Ctrl+T → 현재 task list 보기
"모든 task 보여줘" → lead가 전체 출력
"task list 초기화" → lead가 정리
```

---

## 8. 종료 / 정리

### 한 명만 종료

```
researcher teammate에게 shutdown 요청.
```

Teammate가 approve 또는 reject (이유와 함께).

### 팀 전체 정리

```
clean up the team
```

⚠ 반드시 **lead가** 실행. teammate가 cleanup하면 리소스 inconsistent 가능.

### 죽은 tmux 세션 강제 정리

```bash
tmux ls
tmux kill-session -t <name>
```

---

## 9. Hooks (품질 게이트)

`.claude/settings.json`에 `hooks` 추가:

```json
{
  "hooks": {
    "TeammateIdle": "exit-2-feedback.sh",
    "TaskCreated": "validate-task.sh",
    "TaskCompleted": "verify-completion.sh"
  }
}
```

- `TeammateIdle`: teammate가 idle 직전 — exit 2면 feedback 주고 계속 일하게 함
- `TaskCreated`: task 생성 시 — exit 2면 생성 차단 + feedback
- `TaskCompleted`: complete 표시 시 — exit 2면 차단 + feedback

---

## 10. 알려진 제한 (실험판)

| 제한 | 영향 | 대응 |
|------|------|------|
| `/resume` 시 in-process teammate 복구 안 됨 | 세션 재개 후 lead가 죽은 teammate에 메시지 보낼 수 있음 | "spawn new teammates" 지시 |
| Task 상태 갱신 누락 가능 | 의존 task가 막힘 | 수동 update 또는 lead에게 nudge 요청 |
| Shutdown 느림 | 현재 turn/tool call 끝날 때까지 대기 | 인내 |
| 한 세션에 한 팀만 | 동시 다중 팀 불가 | clean up 후 새 팀 |
| 중첩 팀 불가 | teammate가 자기 팀 생성 X | lead가 모두 spawn |
| Lead 고정 | 생성 세션이 평생 lead | 승계 불가 |
| 권한은 spawn 시점 고정 | per-teammate spawn-time mode 설정 X | spawn 후 개별 변경 가능 |
| Split-pane은 tmux/iTerm2 전용 | VS Code/Windows Terminal/Ghostty 미지원 | in-process로 전환 |

---

## 11. 비용 가이드

- 각 teammate = 별도 Claude 세션 = 풀 컨텍스트 윈도우
- 토큰 비용 = teammate 수 × 평균 컨텍스트
- 5명 Opus 팀 = 단일 Opus 세션의 ~5배 비용

**경험칙**:
- 3~5명: sweet spot
- 5명 초과: 조정 오버헤드가 이득 잠식
- task당 5~6개 work item이 적정 (idle 방지)

---

## 12. 우리 프로젝트 — 5 페르소나 quick start

### 정의된 페르소나 (`.claude/agents/`)

| 파일 | 역할 | 모델 | 색 |
|------|------|------|----|
| `potato-pm.md` | 민지 (PM) | opus | green |
| `potato-quant.md` | 현우 (퀀트) | opus | blue |
| `potato-architect.md` | 지훈 (아키텍트) | opus | purple |
| `potato-devil.md` | 수아 (악마) | opus | red |
| `potato-trader.md` | 태경 (트레이더) | opus | orange |

### 시작하기

```bash
# 1) 활성화 확인 (이미 settings.json에 등록됨)
grep CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS .claude/settings.json

# 2) 새 claude 세션 시작 (이게 lead가 됨)
cd /home/bravopotato/Spaces/finspace/potato-fin
claude

# 3) lead에게 자연어로:
```

**예시 1 — 팀 spawn + 즉시 진단**:
```
potato-pm, potato-quant, potato-architect, potato-devil, potato-trader
5개 subagent로 agent team을 만들어. 각자 보고서/2026-04-21_1954.md 를 Read하고
페르소나 정의에 따라 진단/우려/제안/한 줄 요약 4섹션으로 답하게 한 다음
너가 종합해서 우선순위 매겨.
```

**예시 2 — 토론 유도**:
```
5 페르소나 팀 만들어. 첫 task: "potato-fin 시스템이 정말 가치 있는가?"
teammate끼리 직접 message로 서로 도전하게 해. 내가 개입하기 전에
3 라운드 토론 시켜.
```

**예시 3 — 특정 페르소나 직접 호출**:
```
태경(potato-trader) teammate만 spawn해서 alert_config.json의 손절선이
ATR×2 기준으로 적정한지 검증.
```

### 진단 결과 보관

- `team/findings/YYYY-MM-DD_roundN.md` — 각 라운드 결과 수동 저장
- `team/personas/*.md` — 구버전 (tmux harness 시대) — 참고용 보관

---

## 13. 트러블슈팅

### Teammate 안 나타남
- `Shift+Down`으로 순환해보기 (in-process 모드)
- task가 너무 단순해서 lead가 spawn 안 했을 가능성 — 명시적으로 요청
- `which tmux` 확인 (split-pane 모드)

### 권한 prompt 폭증
- spawn 전에 `.claude/settings.json` `permissions.allow`에 사전 등록

### Teammate가 에러로 멈춤
- `Shift+Down`으로 진입해서 추가 지시
- 또는 replacement teammate spawn

### Lead가 work 다 끝나기 전 종료
- "wait for your teammates to complete their tasks before proceeding"

### Orphan tmux 세션
```bash
tmux ls
tmux kill-session -t <name>
```

---

## 14. 참고

- 공식 문서: <https://code.claude.com/docs/en/agent-teams.md>
- Subagent: <https://code.claude.com/docs/en/sub-agents.md>
- Hooks: <https://code.claude.com/docs/en/hooks.md>
- Settings: <https://code.claude.com/docs/en/settings.md>
- Interactive mode: <https://code.claude.com/docs/en/interactive-mode.md>
