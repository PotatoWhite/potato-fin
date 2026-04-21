# Round 2 — 지훈(아키텍트): Tier 3 Heartbeat 감지 채널 구현

작성자: 지훈 (potato-architect)
날짜: 2026-04-21
대상: Round 1 심각도 ★★★ 1번 (Tier 3 63일 사일런트 다운) 의 실제 코드 조치.

---

## 진단
- `run_report.sh` / `run_korea_report.sh` 는 cron 실행 여부와 무관하게 **자기 죽음을 외부로 알릴 채널이 없다** — exit code가 0이든 1이든 로그 파일 한쪽에 조용히 쌓일 뿐이다.
- 후속 파이프라인(`validate_report.py`, `price_verify.py`, `telegram_notify.sh`)은 모두 **보고서 파일 존재를 전제**로 한다. 파일이 아예 없으면 체인 자체가 트리거되지 않는다 → 공백은 감지 대상에서 빠진다.
- 63일간 alert 0건이 나온 이유: 사용자 입장에서 "어제 보고서 왔나?" 를 매일 수동으로 확인해야 하는 구조였다. Telegram은 성공한 날만 시끄럽고, 실패한 날은 침묵하는 비대칭 알림 채널이었다.

## 우려 (실패 모드)
1. **heartbeat 자체 cron 실패**: `check_heartbeat.sh` 가 cron에서 호출이 안 되면 이 감지 계층도 조용히 죽는다. — 대응: heartbeat 로그(`heartbeat.log`)에 매시간 1줄 append 되는지가 2차 증거. 로그 mtime이 멈추면 cron 자체 문제.
2. **Telegram API 장애**: Anthropic/Telegram side outage 시 HTTP 5xx → 알람 유실. 현재 설계는 "재시도 없이 다음 cron(1시간 후)에 다시 시도". stale 상태는 유지되므로 다음 tick에 다시 보낸다 — 단, `.heartbeat_alert_sent` 상태파일이 이미 stale로 바뀌면 중복 알림이 오지 않는다. **트레이드오프**: 과다 알림 방지 > 유실 복구. 유실이 걱정되면 state flag 대신 "stale은 매 tick 전송" 으로 바꿔야 하지만 그러면 침묵 → 매시간 1번씩 울려 피로.
3. **시스템 시간(clock skew)**: 컨테이너/호스트 시간이 틀어지면 mtime 계산 오차. 현재 STALE 임계 25시간 = 1시간 버퍼로 어느 정도 흡수.
4. **`.env` 누락 / 토큰 회전**: 스크립트 시작 시 토큰 검증 → 없으면 exit 1. 이 경우 cron 로그(`heartbeat.log`)에 에러 남지만 텔레그램으로 알릴 수단이 없음 — 초기 세팅 시 한번만 수동 실행으로 검증 필요.
5. **Korea-only / US-only 단일 실패**: 두 채널을 독립적으로 추적하므로 한쪽이 고장나도 다른 쪽 알림은 정상 동작.

## 제안 (배포 방법 — 3단계)

### Step 1. heartbeat 기록 라인 추가 (사용자 수동)
`run_report.sh` 말미에 아래 1줄을 추가:
```bash
mkdir -p "$LOG_DIR" && date -Iseconds > "$LOG_DIR/.heartbeat_us"
```
`run_korea_report.sh` 말미에도 동일(단 `.heartbeat_kr`):
```bash
mkdir -p "$LOG_DIR" && date -Iseconds > "$LOG_DIR/.heartbeat_kr"
```

**권장 위치**: `exit $EXIT_CODE` **직전** (실패 시에도 한번 정상 완료한 시각이 보존되도록) — 단, "보고서 파일 생성 확인 후에만 heartbeat" 가 더 엄격하다면 `if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then ...` 블록 안으로 이동. 나는 **후자**를 권한다: cron이 돌긴 했으나 Claude가 빈 응답을 주면 heartbeat만 초록이고 실제 보고서는 없는 가짜 성공 상태가 되기 때문.

실제 편집 diff (권장안 — "보고서 존재 확인 후"):

```diff
# run_report.sh (9단계 텔레그램 알림 블록 바로 뒤에 추가)
 if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
     echo "$(date): 텔레그램 전송" >> "$LOG_FILE"
     bash "$STOCK_DIR/telegram_notify.sh" "$STOCK_DIR/$REPORT_FILE" "US 보고서" >> "$LOG_FILE" 2>&1 || true
 fi
+
+# 9.5단계: Tier 3 heartbeat (check_heartbeat.sh 가 이 파일 mtime 으로 사일런트 다운 감지)
+if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
+    date -Iseconds > "$LOG_DIR/.heartbeat_us"
+    echo "$(date): heartbeat 기록: $LOG_DIR/.heartbeat_us" >> "$LOG_FILE"
+fi

 # 10단계: 경제 지표 일정 기반 추가 보고서 스케줄링
```

```diff
# run_korea_report.sh (텔레그램 알림 블록 뒤에 추가)
 if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
     echo "$(date): 텔레그램 전송" >> "$LOG_FILE"
     bash "$STOCK_DIR/telegram_notify.sh" "$STOCK_DIR/$REPORT_FILE" "한국 보고서" >> "$LOG_FILE" 2>&1 || true
 fi
+
+# heartbeat (check_heartbeat.sh 가 감시)
+if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
+    date -Iseconds > "$LOG_DIR/.heartbeat_kr"
+    echo "$(date): heartbeat 기록: $LOG_DIR/.heartbeat_kr" >> "$LOG_FILE"
+fi

 # 30일 이상 된 로그 삭제
```

### Step 2. cron 등록 (사용자 수동 — `crontab -e`)
```cron
# --- Tier 3 heartbeat 감시 (매시간 정각) ---
0 * * * * /home/bravopotato/Spaces/finspace/potato-fin/check_heartbeat.sh >> /home/bravopotato/logs/stock-monitor/heartbeat.log 2>&1
```
주의: 기존 crontab의 `STOCK_DIR` / `LOG_DIR` 정의는 그대로 두고 위 라인만 **Tier 3 Opus 보고서 블록 뒤**에 추가. 스크립트 자체가 절대경로 + 환경변수 fallback을 내장했으므로 cron 변수 참조 문제(기존 `CLAUDE=$STOCK_DIR/...` 리터럴 취급 gotcha) 영향을 받지 않는다.

### Step 3. 초기 검증 (1회 수동)
```bash
# 토큰 정상 로드 + 첫 tick 상태 기록 확인
bash /home/bravopotato/Spaces/finspace/potato-fin/check_heartbeat.sh
tail ~/logs/stock-monitor/heartbeat.log
cat ~/logs/stock-monitor/.heartbeat_alert_sent   # us=missing / kr=missing 이면 첫 알람 1회 발송됨
```
첫 수동 실행에서 텔레그램으로 "사일런트 다운" 경고가 1건 도착해야 정상(아직 heartbeat 파일이 생성된 적 없으므로 missing 상태). 이후 다음 보고서 성공 시 자동으로 "회복" 통지가 1건 더 도착한다.

---

## 작성 파일 목록

| 파일 | 역할 |
|------|------|
| `/home/bravopotato/Spaces/finspace/potato-fin/check_heartbeat.sh` | US/KR heartbeat 파일 mtime 점검, 25h+ stale 시 텔레그램 경고, 회복 시 회복 통지. 상태파일로 중복 알림 방지. chmod +x 완료. |
| `/home/bravopotato/Spaces/finspace/potato-fin/team/findings/round2/architect_heartbeat.md` | 본 요약 (진단/우려/배포 순서/실패모드). |

**수정 필요(diff만 제시, Edit 미적용)**:
- `run_report.sh` — 9단계 뒤에 heartbeat 기록 3줄
- `run_korea_report.sh` — 텔레그램 블록 뒤에 heartbeat 기록 3줄
- `crontab -e` — heartbeat cron 1줄 추가

---

## 한 줄 요약
"이 시스템은 `heartbeat 채널 부재` 때문에 `Tier 3 보고서가 조용히 죽는` 시나리오에서 무너졌다 — 이제 25시간 임계 + Telegram 2채널 양방향 전이 알림으로 그 시나리오의 재현을 10분 내 감지한다."
