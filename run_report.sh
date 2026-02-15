#!/bin/bash
# 일일 투자 보고서 자동 생성 (crontab에서 호출)
# Claude Code CLI 헤드리스 모드로 보고서 작성

set -euo pipefail

# 중첩 세션 방지 해제 (Claude Code 내부에서 실행 시)
unset CLAUDECODE 2>/dev/null || true

STOCK_DIR="/home/bravopotato/Spaces/finspace/potato-fin"
PYTHON="$STOCK_DIR/.venv/bin/python3"
CLAUDE="/home/linuxbrew/.linuxbrew/bin/claude"
LOG_DIR="$HOME/logs/stock-monitor"

mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/report_$(date +%Y%m%d_%H%M%S).log"


echo "$(date): 보고서 생성 시작" >> "$LOG_FILE"

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

# 4단계: 현금 잔고 + 스케줄 오버라이드 읽기
CASH_DATA=$(cat "$STOCK_DIR/portfolio_config.json" 2>/dev/null || echo '{"cash":{"USD":0}}')
SCHEDULE_OVERRIDE=$(cat "$STOCK_DIR/schedule_override.json" 2>/dev/null || echo '{}')
echo "$(date): 현금 설정: $CASH_DATA" >> "$LOG_FILE"

# 5단계: 직전 보고서 경로 확인 (예측 회고용)
PREV_REPORT=$(ls -1 "$STOCK_DIR/보고서/"*.md 2>/dev/null | tail -1 || echo "")
echo "$(date): 직전 보고서: $PREV_REPORT" >> "$LOG_FILE"

# 5.1단계: Tier 1 감시 데이터 구조화 요약 (장전 브리핑 + 장중 모니터링 결과)
echo "$(date): Tier 1 데이터 로드" >> "$LOG_FILE"
REPORT_DATE_FOR_MONITOR=$(TZ=Asia/Seoul date +%Y-%m-%d)
MONITOR_SUMMARY=$("$PYTHON" -c "
from news_monitor import format_daily_briefing
print(format_daily_briefing('$REPORT_DATE_FOR_MONITOR'))
" 2>/dev/null || echo "Tier 1 데이터 로드 실패")
echo "$(date): Tier 1 요약: ${#MONITOR_SUMMARY}자" >> "$LOG_FILE"

# 5.5단계: 투자 테제 로드
echo "$(date): 투자 테제 로드" >> "$LOG_FILE"
THESIS_SUMMARY=$("$PYTHON" -c "
from update_thesis import format_thesis_summary
print(format_thesis_summary())
" 2>/dev/null || echo "투자 테제 없음")
echo "$(date): 테제: ${#THESIS_SUMMARY}자" >> "$LOG_FILE"

# 5.6단계: 메르 블로그 RSS 피드 (최근 3일 글 제목 수집)
echo "$(date): 메르 블로그 RSS 수집" >> "$LOG_FILE"
MER_BLOG=$("$PYTHON" -c "
import urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
try:
    url = 'https://rss.blog.naver.com/ranto28'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = resp.read().decode('utf-8')
    root = ET.fromstring(data)
    items = root.find('channel').findall('item')
    kst = timezone(timedelta(hours=9))
    cutoff = datetime.now(kst) - timedelta(days=3)
    results = []
    for item in items:
        title = item.find('title').text or ''
        pub_str = item.find('pubDate').text if item.find('pubDate') is not None else ''
        try:
            from email.utils import parsedate_to_datetime
            pub_dt = parsedate_to_datetime(pub_str)
            if pub_dt < cutoff:
                continue
            date_str = pub_dt.strftime('%m/%d %H:%M')
        except:
            date_str = ''
        results.append(f'- [{date_str}] {title}')
    if results:
        print('메르의 블로그 (blog.naver.com/ranto28) 최근 글:')
        print('\n'.join(results))
    else:
        print('메르 블로그: 최근 3일 내 글 없음')
except Exception as e:
    print(f'메르 블로그 RSS 수집 실패: {e}')
" 2>/dev/null || echo "메르 블로그 RSS 수집 실패")
echo "$MER_BLOG" >> "$LOG_FILE"

# 6단계: Claude Code로 보고서 생성
REPORT_DATE=$(TZ=Asia/Seoul date +%Y-%m-%d)
REPORT_TIME=$(TZ=Asia/Seoul date +%H%M)
REPORT_FILE="보고서/${REPORT_DATE}_${REPORT_TIME}.md"
echo "$(date): Claude 보고서 작성 시작 → $REPORT_FILE" >> "$LOG_FILE"
"$CLAUDE" -p "보고서 만들어줘. 아래는 yfinance 실측 데이터입니다.

=== 보고서 파일명 (반드시 이 경로에 저장) ===
$REPORT_FILE
현재 한국시간(KST): ${REPORT_DATE} ${REPORT_TIME:0:2}:${REPORT_TIME:2:2}
보고서 제목의 날짜도 이 KST 날짜를 사용하라.

WebSearch를 충분히 활용하여 다음을 반드시 조사하라 (최소 52건):

[최근 발표 경제지표 수집 — 5건]
CLAUDE.md의 '최근 발표 경제지표 대시보드' 템플릿의 모든 행을 수치로 채워라.
반드시 아래를 WebSearch하라:
0-1. \"US nonfarm payrolls January 2026 actual\" (NFP, 실업률, 시간당 임금)
0-2. \"US ISM manufacturing services PMI January 2026\" (제조업/서비스업 PMI)
0-3. \"US initial jobless claims latest February 2026\" (주간 실업수당)
0-4. \"US retail sales consumer confidence January 2026\" (소매판매, 소비자신뢰)
0-5. \"US PCE inflation December 2025 actual\" (PCE/Core PCE 최신)
각 지표의 실제값/컨센서스/직전치를 정확히 기입하고, 서프라이즈(상회/부합/하회)와 해석을 작성하라.
종합 진단에서 고용/인플레/성장/소비를 각각 한줄로 판정하고, 연준 금리 경로 시사점을 도출하라.

[기본 리서치 — 18건]
1. 매크로: 이번 주 경제지표(CPI/PPI/고용), 연준 동향, 금리/국채
2. 정치/스캔들: 트럼프 행정부 스캔들, 의회 갈등, SEC/DOJ 조사, CEO 스캔들, DOGE, 셧다운 리스크
3. 지정학: 관세, 무역전쟁, 우크라이나, 중동, 대만
4. 보유종목 뉴스: 실적/소송/규제/내부자 스캔들/경영진 변동
5. 환율/원자재/암호화폐
6. 기관흐름: 13F, ETF 자금흐름, 다크풀, 이상 옵션
7. 숨은진주: 기관 매집+주가 미반응, 내부자 매수, 숏스퀴즈 후보

[인덱스 심층 해부 — 7건]
CLAUDE.md의 '인덱스 심층 해부' 템플릿에 따라 아래를 반드시 조사하라:
8. 시장 폭: \"S&P 500 stocks above 200 day moving average\" + \"S&P 500 equal weight vs cap weight RSP SPY ratio 2026\"
9. 미 정부 신뢰: \"US Treasury auction bid to cover ratio recent\" + \"US CDS spread 2026\"
10. 달러 이탈: \"central bank gold purchases 2026\" + \"de-dollarization yuan trade settlement\"
11. 유동성/신용: \"Fed reverse repo balance\" + \"high yield credit spread\" + \"MOVE index\"
이 결과로 '인덱스 심층 해부' 섹션의 모든 테이블을 수치로 채우고, 종합 판단(건강도/정부신뢰/유동성)을 작성하라.
인덱스 지수가 올라도 시장 폭이 약하면 \"허약한 상승\"으로 판정.
DXY 약세 + 금 강세 + 국채 수요 약화 = 정부 신뢰 하락 시그널로 판정.

[버티컬 심층 리서치 — 비중 상위 5종목, 각 2건 = 10건]
CLAUDE.md의 '종목별 버티컬 분석 맵'을 참조하여, 포트폴리오 비중 상위 5종목에 대해 추가 WebSearch를 수행하라:
- 각 종목의 [업스트림 공급] 이슈 1건 + [다운스트림 수요/경쟁] 동향 1건
- 예: NVDA → \"data center capex spending 2026\" + \"TSMC CoWoS capacity utilization 2026\"
- 예: MSFT → \"Azure growth rate Q1 2026\" + \"Copilot enterprise adoption 2026\"
- 예: GOOGL → \"digital ad market growth 2026\" + \"Google Cloud revenue 2026\"
- 이 결과를 해당 종목의 '버티컬 분석' 행에 반영

종목별 대응 전략 테이블에 반드시 아래 행을 추가하라:
| 버티컬 분석 | [업스트림] 공급 이슈 / [다운스트림] 수요 동향 / [경쟁] 점유율 변화 / [선행지표] 핵심 데이터 |
이 행은 CLAUDE.md 버티컬 맵의 카테고리를 기준으로 최신 데이터를 채워 작성한다.

보고서에 정확한 수치로 반영하고, 숨은진주 발굴 시 공매도/내부자거래/기관보유 데이터를 반드시 검증하세요.
Finnhub 뉴스 센티먼트가 [6]에 포함되어 있다. 스캔들 감지 종목은 반드시 해당 뉴스를 보고서에 반영하라.

[예측 시장 (Polymarket) — 2건]
실제 돈이 걸린 예측 시장 확률을 조사하여 이벤트 시나리오의 가중치로 활용하라.
12. \"Polymarket Fed rate cut 2026 odds recession probability\"
13. \"Polymarket tariff government shutdown geopolitics 2026\"
결과를 보고서의 '예측 시장 확률 (Polymarket)' 섹션에 정리하고,
확률 vs 기관 포지션 괴리가 있으면 역발상 기회로 분석하라.

[인덱스별 숨은 진주 — 12건]
CLAUDE.md의 '숨은 진주 — 인덱스별 분리 발굴' 템플릿에 따라 4개 인덱스별로 숨은 진주를 발굴하라.

★★★ 숨은 진주 필수 규칙 ★★★
- 보유 종목(035420.KS,195940.KQ,429760.KS,1377.T,BAYN.DE,BOTZ,CVX,GOOGL,MSFT,NVDA,PLTR,QCOM,SLV,TSLA,UNH,WRB,XOM) 절대 포함 금지
- 시총 \$100B 이상 대형주(AAPL,AMZN,META,GOOG,TSMC,AVGO 등) 포함 금지
- 섹터 ETF(XLK,XLB,XLP,IWM 등) 포함 금지 — 개별 종목 티커만 제시
- \"다수\", \"여러 종목\" 같은 모호한 표현 금지 — 반드시 구체적 티커+시총+수치
- 각 인덱스에서 최소 3개 종목, 합계 최소 12개 종목 제시
- Russell 2000은 핵심 광맥 — 최소 5개 소형주 구체적 티커 필수

14. Dow 30 역발상 (2건):
    \"Dow 30 worst performing stocks February 2026 institutional buying\"
    \"Dow Jones component insider purchase SEC filing 2026\"
    → 최근 30일 하위 5종목 중 기관 재진입 + 내부자 매수 조합 찾기
15. S&P 500 로테이션 (2건):
    \"S&P 500 index rebalancing additions March 2026 candidates\"
    \"S&P 500 mid cap stocks institutional accumulation undervalued PEG below 1 2026\"
    → 편입 예정 종목 + 기관 언더웨이트→오버웨이트 전환 종목
16. Nasdaq 턴어라운드 (3건):
    \"Nasdaq mid cap earnings turnaround loss to profit 2026\"
    \"AI infrastructure second tier stocks cooling power cables 2026 undervalued\"
    \"semiconductor equipment materials mid cap undervalued institutional buying 2026\"
    → 적자→흑자 전환 종목 + AI 밸류체인 2~3선주 (시총 \$5B~\$50B)
17. Russell 2000 소형주 광맥 (3건) — 가장 깊게:
    \"SEC Form 4 insider buying small cap \$100K February 2026\"
    \"Russell 2000 short interest 20% earnings beat short squeeze candidate 2026\"
    \"small cap micro cap insider cluster buying institutional new position 2026\"
    → 내부자 \$100K+ 자발적 매수 + 공매도 20%+ & 실적 Beat 조합 (구체적 티커 5개+)
    → 각 종목의 시총, 일 거래량, 스프레드(유동성 리스크) 반드시 표기
18. 글로벌 숨은 진주 (2건) — 미국 외 시장:
    \"Europe small cap insider buying undervalued institutional accumulation 2026\"
    \"Japan Korea small cap foreign buying undervalued 2026\"
    → 유럽/일본/한국 소형주 중 기관 매집 + 저평가 종목 (최소 2개)

인덱스 간 크로스 시그널(IWM/SPY, QQQ/DIA, RSP/SPY 비율)도 분석하라.

=== 보고서 품질 교훈 (반드시 준수) ===
① 예상 종가 편향 보정: 악재(CPI 상회, 다운그레이드 등) 직후 예상 종가를 산출할 때 과도한 하방 편향 금지.
   시장은 악재를 예상보다 빠르게 소화하는 경향이 있다. \"시장 소화\" 시나리오에 50%+ 확률 부여하라.
   예상 종가 산출 시: 기술적 신호 점수가 양수(+)면 현재가 부근~고가 쪽, 음수(-)면 현재가 부근~저가 쪽으로 추정.
   이벤트 충격을 과대 반영하지 말 것.

   **변동성 높은 종목(ATR% > 5%) 예상 범위 확대**: TSLA, PLTR 등 고변동성 종목은 5일 예상 범위를 ATR × 3으로 확대하라.
   기술적 점수만으로 좁은 범위를 산출하지 말고, 역사적 변동폭(ATR%)을 반영하여 ±15% 이상 여유를 둘 것.
   예: TSLA ATR% = 6.2% → 5일 예상 범위 = 현재가 × (1 ± 0.15) 이상으로 설정.

② 경제지표 일정 교차검증: WebSearch로 경제지표 일정을 조사할 때 반드시 2개 이상 소스에서 확인하라.
   특히 \"연기/취소/변경\" 정보는 공식 소스(BLS.gov, FederalReserve.gov)를 우선하라.
   단일 검색 결과만으로 일정 변경을 단정하지 말 것.

③ ETF 자금흐름 교차검증: ETF 자금흐름(QQQ/SPY/XLK 등) 수치를 인용할 때 반드시 출처와 기준일을 명시하라.
   같은 ETF라도 소스에 따라 상반된 수치가 나올 수 있다. \"5일 흐름 +\$5.1B (출처: etf.com, 기준: 2/11)\" 형태로 표기.

④ 환율 영향 명시: 포트폴리오 총액 변동 분석 시 \"주가 변동분\"과 \"환율 변동분\"을 분리하여 표시하라.
   USD 82%+ 포트폴리오는 원/달러 1원 변동만으로도 수십만원 차이가 난다.

⑤ 이전 보고서 회고: 직전 보고서의 예상 종가 vs 실제 종가를 비교하는 \"예측 회고\" 섹션을 포함하라.
   맞춘 예측과 빗나간 예측을 분석하여 다음 예측 정확도를 개선하라.

=== 직전 보고서 (예측 회고용) ===
직전 보고서 경로: $PREV_REPORT
이 파일을 Read하여 '예상 거래 범위' 테이블의 예상 종가를 추출하고, 현재 실제 종가와 비교하여 '이전 보고서 예측 회고' 섹션을 작성하라.
직전 보고서가 없으면 이 섹션은 생략.

=== 종목별 종합 진단 지침 ===
종목별 대응 전략 테이블에 반드시 아래 4가지 진단을 포함하라:
① 셰이크아웃 판별: 공매도 <3% + 기관 유지/증가 + 펀더멘탈 양호 → 기술적 약세는 기관이 개미 털고 매집하는 중 (매수 기회)
② 분배 판별: 내부자 매도만 + 공매도 높음(>10%) + 긍정 뉴스 범람 → 기관이 물량 넘기는 중 (추격 매수 금지)
③ 성장함정 판별: 매출 성장하지만 FCF 적자 + 부채 과다 + 수익성 전환 불확실 → 매출에 속지 말 것
④ 재무 건전성: FCF(+/-), 부채비율(D/E), 유동비율, 영업이익률 → 체력 진단 (건전/보통/위험)
종합 진단 한줄: 위 4가지를 종합하여 (셰이크아웃/분배/성장함정/건전성장/혼재) 중 하나로 판정

=== 현금 관리 지침 ===
아래 현금 잔고를 포함하여 '현금 관리 & 투자 배분' 섹션을 반드시 작성하라.
- 현재 자산 배분 (주식 총액 / 현금 / 총 자산 / 현금 비중)
- 포트폴리오 진단 (섹터 집중도, 상위5종목 비중, 통화 편중)
- 현금 3단계 분할 배분 제안 (즉시/이벤트후/예비금) — 구체적 티커, 금액, 조건, 근거
- 종목별 예상 거래 범위 (ATR 기반 저가/고가/예상종가/손절선/목표가/방향성) — 예상 종가는 기술적 점수+이벤트+거래량+센티먼트 종합 추정. 손절선과 목표가는 종목별 대응 전략의 기술적 레벨을 그대로 표기
현금 잔고: $CASH_DATA

=== 포트폴리오 현황 (총액/손익/비중/배당) ===
$PORTFOLIO_DATA

=== 시장 데이터 + 종목 검증 ===
$MARKET_DATA

=== 경제 지표 일정 변경 감지 지침 ===
WebSearch로 이번 주 경제 지표 발표 일정을 조사할 때, 아래 정적 일정과 다른 점이 있으면
(셧다운 연기, BLS 일정 변경, 임시 발표 추가 등)
schedule_override.json 파일을 업데이트하라.

현재 오버라이드: $SCHEDULE_OVERRIDE

형식:
{
  \"_updated\": \"YYYY-MM-DD\",
  \"_source\": \"보고서 파일명\",
  \"overrides\": [{\"original_date\":\"YYYY-MM-DD\", \"new_date\":\"YYYY-MM-DD\", \"new_time\":\"HH:MM\", \"name\":\"지표명\", \"impact\":\"HIGH\", \"reason\":\"사유\"}],
  \"additions\": [{\"date\":\"YYYY-MM-DD\", \"time\":\"HH:MM\", \"name\":\"지표명\", \"impact\":\"HIGH\", \"reason\":\"사유\"}],
  \"cancellations\": [{\"date\":\"YYYY-MM-DD\", \"name\":\"지표명\", \"reason\":\"사유\"}]
}

시간은 KST 기준. 변경 없으면 파일 수정하지 말 것.

=== 메르 블로그 참고 토픽 (최근 3일) ===
아래는 금융 전문가 '메르'(삼성/GE 위험관리 출신, 금융사 임원, 30조원+ 투융자 검토 경력)의 최근 블로그 글 제목이다.

★ 토픽 선별 기준 (WebSearch 낭비 방지) ★
아래 토픽 중 다음 조건을 모두 충족하는 것만 추가 조사하라:
1. 보고서의 다른 섹션(경제지표 대시보드, 매크로 요약 등)에서 이미 다루지 않는 새로운 각도의 정보
2. 보유 종목 또는 포트폴리오에 직접적 영향이 있는 주제 (예: HBM→NVDA, 국채매각→금리/환율)
3. 아직 시장이 완전히 소화하지 않은 진행 중인 이슈 (발표 후 2일+ 경과한 경제지표 결과는 제외)
제외 대상: 이미 발표된 경제지표 해석, 중복 제목, 건강/음식/부동산 등 비관련 주제, 한국 내수 부동산
선별 결과 0건이면 이 섹션 자체를 생략하라. 최대 2건만 추가 WebSearch.
메르 블로그 원문을 인용하지 말고 독자적으로 조사한 내용만 작성할 것.
$MER_BLOG

=== Tier 1 장중 감시 누적 데이터 ===
아래는 news_monitor.py가 30분 간격으로 수집한 오늘의 누적 데이터이다.
가격 이상(±3%), 거래량 스파이크, 긴급 뉴스, 경제지표 발표 결과가 포함되어 있다.
이 데이터를 보고서 분석에 반영하되, WebSearch로 교차검증하라.
$MONITOR_SUMMARY

=== 투자 테제 (이전 보고서 누적 판단) ===
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
    --max-budget-usd 15.0 \
    >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "$(date): 보고서 생성 완료 (exit=$EXIT_CODE)" >> "$LOG_FILE"

# 6.5단계: 가격 검증 + 자동 보정
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
    echo "$(date): 가격 검증 + 자동 보정" >> "$LOG_FILE"
    "$PYTHON" "$STOCK_DIR/price_verify.py" "$STOCK_DIR/$REPORT_FILE" --fix >> "$LOG_FILE" 2>&1 || true
fi

# 7단계: 투자 테제 업데이트
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
    echo "$(date): 투자 테제 업데이트" >> "$LOG_FILE"
    "$PYTHON" "$STOCK_DIR/update_thesis.py" --report "$STOCK_DIR/$REPORT_FILE" >> "$LOG_FILE" 2>&1 || true
fi

# 8단계: 보고서 검증
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
    echo "$(date): 보고서 검증" >> "$LOG_FILE"
    "$PYTHON" "$STOCK_DIR/validate_report.py" "$STOCK_DIR/$REPORT_FILE" --notify --type us >> "$LOG_FILE" 2>&1 || true
fi

# 8.5단계: 포트폴리오 스냅샷
echo "$(date): 포트폴리오 스냅샷" >> "$LOG_FILE"
"$PYTHON" "$STOCK_DIR/portfolio_tracker.py" --snapshot >> "$LOG_FILE" 2>&1 || true

# 9단계: 텔레그램 알림
if [[ $EXIT_CODE -eq 0 && -f "$STOCK_DIR/$REPORT_FILE" ]]; then
    echo "$(date): 텔레그램 전송" >> "$LOG_FILE"
    bash "$STOCK_DIR/telegram_notify.sh" "$STOCK_DIR/$REPORT_FILE" "US 보고서" >> "$LOG_FILE" 2>&1 || true
fi

# 10단계: 경제 지표 일정 기반 추가 보고서 스케줄링
echo "$(date): 경제 지표 스케줄 업데이트" >> "$LOG_FILE"
"$PYTHON" "$STOCK_DIR/schedule_reports.py" >> "$LOG_FILE" 2>&1 || true

# 30일 이상 된 로그 삭제
find "$LOG_DIR" -name "report_*.log" -mtime +30 -delete 2>/dev/null || true

exit $EXIT_CODE
