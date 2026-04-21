#!/bin/bash
# 한국시장 일일 보고서 자동 생성 (평일 15:35 KST)
# Claude Code CLI 헤드리스 모드로 한국시장 특화 보고서 작성

set -euo pipefail

# 중첩 세션 방지 해제 (Claude Code 내부에서 실행 시)
unset CLAUDECODE 2>/dev/null || true

STOCK_DIR="${STOCK_DIR:-/home/bravopotato/Spaces/finspace/potato-fin}"
PYTHON="${PYTHON:-$STOCK_DIR/.venv/bin/python3}"
CLAUDE="${CLAUDE:-$(command -v claude 2>/dev/null || echo /home/bravopotato/.npm-global/bin/claude)}"
LOG_DIR="${LOG_DIR:-$HOME/logs/stock-monitor}"

mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/korea_report_$(date +%Y%m%d_%H%M%S).log"


echo "$(date): 한국시장 보고서 생성 시작" >> "$LOG_FILE"

cd "$STOCK_DIR"

# 1단계: 주가 업데이트 (포트폴리오 현황 캡처)
echo "$(date): 주가 업데이트 실행" >> "$LOG_FILE"
PORTFOLIO_DATA=$("$PYTHON" "$STOCK_DIR/주가_업데이트.py" 2>/dev/null)
echo "$PORTFOLIO_DATA" >> "$LOG_FILE"

# 2단계: 기술분석 + alert_config.json 갱신 (.tech_scores.json 생성)
echo "$(date): 기술분석 실행" >> "$LOG_FILE"
TECH_DATA=$("$PYTHON" "$STOCK_DIR/technical_analysis.py" --update-alerts 2>/dev/null)
echo "$TECH_DATA" >> "$LOG_FILE"

# 3단계: 시장 데이터 + 종목 검증 수집 (.tech_scores.json 읽어서 종합 점수 산출)
echo "$(date): 시장 데이터 + 종목 검증 수집" >> "$LOG_FILE"
MARKET_DATA=$("$PYTHON" "$STOCK_DIR/market_data.py" 2>/dev/null)
echo "$MARKET_DATA" >> "$LOG_FILE"

# 4단계: 현금 잔고 읽기
CASH_DATA=$(cat "$STOCK_DIR/portfolio_config.json" 2>/dev/null || echo '{"cash":{"USD":0}}')
echo "$(date): 현금 설정: $CASH_DATA" >> "$LOG_FILE"

# 5단계: 직전 한국 보고서 경로 확인 (예측 회고용)
PREV_REPORT=$(ls -1 "$STOCK_DIR/보고서/한국/"*.md 2>/dev/null | tail -1 || echo "")
echo "$(date): 직전 한국 보고서: $PREV_REPORT" >> "$LOG_FILE"

# 6단계: 한국시장 리서치 파일 (전략 참조용)
KOREA_RESEARCH=$(ls -1 "$STOCK_DIR/한국시장_리서치"*.md 2>/dev/null | tail -1 || echo "")
echo "$(date): 한국시장 리서치: $KOREA_RESEARCH" >> "$LOG_FILE"

# 6.5단계: 투자 테제 로드
echo "$(date): 투자 테제 로드" >> "$LOG_FILE"
THESIS_SUMMARY=$("$PYTHON" -c "
from update_thesis import format_thesis_summary
print(format_thesis_summary())
" 2>/dev/null || echo "투자 테제 없음")

# 6.6단계: Tier 1 감시 데이터 구조화 요약
echo "$(date): Tier 1 데이터 로드" >> "$LOG_FILE"
REPORT_DATE_FOR_MONITOR=$(TZ=Asia/Seoul date +%Y-%m-%d)
MONITOR_SUMMARY=$("$PYTHON" -c "
from news_monitor import format_daily_briefing
print(format_daily_briefing('$REPORT_DATE_FOR_MONITOR'))
" 2>/dev/null || echo "Tier 1 데이터 로드 실패")

# 7단계: Claude Code로 한국시장 보고서 생성
REPORT_DATE=$(TZ=Asia/Seoul date +%Y-%m-%d)
REPORT_TIME=$(TZ=Asia/Seoul date +%H%M)
REPORT_FILE="보고서/한국/${REPORT_DATE}_${REPORT_TIME}.md"
echo "$(date): Claude 한국 보고서 작성 시작 → $REPORT_FILE" >> "$LOG_FILE"
"$CLAUDE" -p "한국시장 일일 보고서를 만들어줘. 아래는 yfinance 실측 데이터입니다.

=== 보고서 파일명 (반드시 이 경로에 저장) ===
$REPORT_FILE
현재 한국시간(KST): ${REPORT_DATE} ${REPORT_TIME:0:2}:${REPORT_TIME:2:2}
보고서 제목의 날짜도 이 KST 날짜를 사용하라.

WebSearch를 충분히 활용하여 다음을 반드시 조사하라 (최소 20건):

[기본 리서치 — 12건]
1. 한국 매크로: 한국은행 기준금리, 한국 CPI/PPI, 수출입 동향, 경상수지, 고용률
2. KOSPI/KOSDAQ: 당일 시장 동향, 외국인/기관/개인 수급, 프로그램매매, 선물 포지션
3. 한국 정치/정책: 밸류업 정책, 금투세, 배당 분리과세, 공매도 규제, 정국 동향
4. 보유 한국종목 뉴스: 삼성전자(005930.KS), SK하이닉스(000660.KS), NAVER(035420.KS), HK이노엔(195940.KQ), PLUS S&P500 ETF(429760.KS) + 편입 예정 종목
5. 한국 섹터: 금융/조선/방산/바이오/원전/반도체 당일 동향
6. 한국 기관자금흐름: 외국인 순매수/매도 상위, 기관 순매수, 공매도 상위
7. 한국 숨은진주 (KOSPI): 외국인 순매도 과잉 + 기관 매집 + 밸류업 저PBR 종목
7-1. 한국 숨은진주 (KOSDAQ): 기관 5일+ 연속 순매수 + 개인 투매 + 코스닥150 편입후보
8. 환율: USD/KRW, JPY/KRW, 환율 전망 및 포트폴리오 영향
9. 중국 영향: 중국 경기지표, 한중 무역, 중국 프록시 종목 영향

[버티컬 심층 리서치 — 보유 한국종목 + 주요 편입후보, 각 2건 = 6건+]
docs/vertical_map.md의 '종목별 버티컬 분석 맵'을 참조하여 추가 WebSearch를 수행하라:
- 삼성전자: \"삼성전자 파운드리 수율 HBM 점유율 2026\" + \"삼성전자 반도체 실적 전망 2026\"
- SK하이닉스: \"SK하이닉스 HBM3E 출하량 엔비디아 2026\" + \"SK하이닉스 DRAM 가격 전망 2026\"
- NAVER: \"네이버 AI 브리핑 침투율 광고 매출 2026\" + \"네이버 커머스 GMV 쿠팡 점유율 2026\"
- HK이노엔: \"케이캡 처방액 시장점유율 2026\" + \"HK이노엔 미국 FDA NDA 진행 2026\"
- 편입후보 (KB금융/HD한국조선해양 등): 해당 종목의 핵심 수요 드라이버 1건씩

종목별 분석 테이블에 반드시 아래 행을 추가하라:
| 버티컬 분석 | [사업부별 수요] 핵심 사업 동향 / [경쟁] 점유율 변화 / [선행지표] 최신 데이터 |
이 행은 docs/vertical_map.md 버티컬 맵의 카테고리를 기준으로 최신 데이터를 채워 작성한다.

보고서에 정확한 수치로 반영하고, 한국 종목의 외국인/기관 수급 데이터를 반드시 검증하세요.
docs/report_template_kr.md의 '한국시장 일일 보고서' 템플릿을 따라 작성하세요.

=== 보고서 품질 교훈 (반드시 준수) ===
① 한국 시장 수급은 외국인 > 기관 > 개인 순으로 신뢰. 외국인 연속 순매수/매도 일수 표기.
   **변동성 높은 종목(ATR% > 5%) 예상 범위 확대**: 고변동성 종목은 5일 예상 범위를 ATR × 3으로 확대하라.
   역사적 변동폭을 반영하여 ±15% 이상 여유를 둘 것.
② 환율 영향 명시: USD/KRW 변동이 해외주식 비중이 높은 포트폴리오에 미치는 영향 분석.
③ 코리아 디스카운트 요인(지배구조, 배당, 정치 리스크) 변화 감지 시 반영.
④ 프로그램매매 만기/롤오버, 옵션 만기일 효과 등 한국 특유 수급 이벤트 표기.

=== 직전 한국 보고서 (예측 회고용) ===
직전 보고서 경로: $PREV_REPORT
이 파일을 Read하여 '예상 거래 범위' 테이블의 예상 종가를 추출하고, 현재 실제 종가와 비교하여 '이전 보고서 예측 회고' 섹션을 작성하라.
직전 보고서가 없으면 이 섹션은 생략.

=== 한국시장 리서치 (편입 후보 참조) ===
리서치 파일 경로: $KOREA_RESEARCH
이 파일이 있으면 Read하여 편입 후보 종목의 당일 동향을 '편입 후보 종목 모니터링' 섹션에 반영하라.
파일이 없으면 이 섹션은 WebSearch로 자체 조사.

=== 종목별 종합 진단 지침 ===
종목별 분석 테이블에 반드시 아래 4가지 진단을 포함하라:
① 셰이크아웃 판별: 공매도 낮음 + 기관/외국인 유지/증가 + 펀더멘탈 양호 → 기술적 약세는 매수 기회
② 분배 판별: 내부자 매도만 + 공매도 높음 + 긍정 뉴스 범람 → 추격 매수 금지
③ 성장함정 판별: 매출 성장하지만 FCF 적자 + 부채 과다 → 매출에 속지 말 것
④ 재무 건전성: FCF, 부채비율, 유동비율, 영업이익률 → 체력 진단

=== 오늘의 1억 포트폴리오 (한국시장, 매 보고서 필수) ===
'오늘 1억이 있다면' 섹션을 반드시 작성하라.
한국시장 종목 위주로 1억(₩100,000,000)을 지금 당장 투자한다면 어떻게 배분할지 제시.
보유 한국종목 + 신규 한국종목(숨은진주) + 현금(10~30%) 혼합.
각 종목 매수가는 당일 기술적 분석 기반 구체적 가격, 3분할 원칙 적용.

=== 현금 관리 지침 ===
아래 현금 잔고를 참조하여 한국 종목 매수 제안 시 구체적 금액/수량/조건을 명시하라.
현금 잔고: $CASH_DATA

=== 포트폴리오 현황 ===
$PORTFOLIO_DATA

=== 시장 데이터 + 종목 검증 ===
$MARKET_DATA

=== Tier 1 장중 감시 누적 데이터 ===
$MONITOR_SUMMARY

=== 투자 테제 (누적 판단) ===
이 테제는 이전 보고서들의 예측/판단을 누적 추적한 것이다.
- 확신도(conviction)가 7+ 종목은 근거 없이 판단 변경 금지
- accuracy의 편향(bias)을 발견하면 예상 종가를 보정하라
- 이전 판단과 달라질 경우 변경 사유를 명시하라
$THESIS_SUMMARY

=== 기술분석 ===
$TECH_DATA" \
    --allowedTools "WebSearch,WebFetch,Bash,Write,Read,Edit,Glob,Grep" \
    --permission-mode bypassPermissions \
    --model opus \
    --max-budget-usd 8.0 \
    >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "$(date): 한국 보고서 생성 완료 (exit=$EXIT_CODE)" >> "$LOG_FILE"

# 가격 검증 + 자동 보정
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
    echo "$(date): 가격 검증 + 자동 보정" >> "$LOG_FILE"
    "$PYTHON" "$STOCK_DIR/price_verify.py" "$STOCK_DIR/$REPORT_FILE" --fix >> "$LOG_FILE" 2>&1 || true
fi

# 투자 테제 업데이트
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
    echo "$(date): 투자 테제 업데이트" >> "$LOG_FILE"
    "$PYTHON" "$STOCK_DIR/update_thesis.py" --report "$STOCK_DIR/$REPORT_FILE" >> "$LOG_FILE" 2>&1 || true
fi

# 보고서 검증
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
    echo "$(date): 보고서 검증" >> "$LOG_FILE"
    "$PYTHON" "$STOCK_DIR/validate_report.py" "$STOCK_DIR/$REPORT_FILE" --notify --type kr >> "$LOG_FILE" 2>&1 || true
fi

# 포트폴리오 스냅샷
echo "$(date): 포트폴리오 스냅샷" >> "$LOG_FILE"
"$PYTHON" "$STOCK_DIR/portfolio_tracker.py" --snapshot >> "$LOG_FILE" 2>&1 || true

# 텔레그램 알림
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
    echo "$(date): 텔레그램 전송" >> "$LOG_FILE"
    bash "$STOCK_DIR/telegram_notify.sh" "$STOCK_DIR/$REPORT_FILE" "한국 보고서" >> "$LOG_FILE" 2>&1 || true
fi

# Tier 3 heartbeat (check_heartbeat.sh 가 이 파일 mtime 으로 사일런트 다운 감지)
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
    date -Iseconds > "$LOG_DIR/.heartbeat_kr"
    echo "$(date): heartbeat 기록: $LOG_DIR/.heartbeat_kr" >> "$LOG_FILE"
fi

# 30일 이상 된 로그 삭제
find "$LOG_DIR" -name "korea_report_*.log" -mtime +30 -delete 2>/dev/null || true

exit $EXIT_CODE
