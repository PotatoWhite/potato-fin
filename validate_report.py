#!/usr/bin/env python3
"""
보고서 품질 자동 검증 (Report Validator)

보고서 생성 후 필수 섹션/데이터 존재 여부를 확인하고,
문제 발견 시 텔레그램 경고를 전송한다.

Usage:
    python3 validate_report.py <report_path>           # 검증 후 결과 출력
    python3 validate_report.py <report_path> --notify   # 실패 시 텔레그램 경고
    python3 validate_report.py <report_path> --type kr  # 한국 보고서 검증
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

STOCK_DIR = Path(__file__).resolve().parent

# ── 보유 종목 ──────────────────────────────────────────────
TICKERS_US = ["NVDA", "MSFT", "GOOGL", "TSLA", "PLTR", "CVX", "XOM",
              "UNH", "WRB", "QCOM", "BOTZ", "SLV", "BAYN.DE", "1377.T"]
TICKERS_KR = ["NAVER", "HK이노엔", "035420", "195940", "429760"]

# ── US 보고서 필수 섹션 ────────────────────────────────────
US_REQUIRED_SECTIONS = [
    ("오늘의 핵심 이벤트", r'##\s*오늘의 핵심 이벤트'),
    ("매크로 환경 요약", r'##\s*매크로 환경 요약'),
    ("정치/통상/지정학 종합", r'##\s*정치.?통상.?지정학'),
    ("경제지표 대시보드", r'##\s*최근 발표 경제지표'),
    ("인덱스 심층 해부", r'##\s*인덱스 심층 해부'),
    ("종목별 대응 전략", r'##\s*종목별 대응 전략'),
    ("역발상 분석", r'##\s*역발상 분석'),
    ("포트폴리오 리스크", r'##\s*포트폴리오 리스크'),
    ("현금 관리", r'##\s*현금 관리'),
    ("5거래일 전망", r'##.*5거래일 전망|####\s*종목별 5거래일'),
    ("숨은 진주", r'##\s*숨은 진주'),
    ("연간 로드맵", r'##\s*2026 연간 로드맵'),
    ("예측 시장", r'##\s*예측 시장 확률'),
]

# ── 한국 보고서 필수 섹션 ──────────────────────────────────
KR_REQUIRED_SECTIONS = [
    ("오늘의 핵심 이벤트", r'##\s*오늘의 핵심 이벤트'),
    ("한국 매크로 요약", r'##\s*한국 매크로'),
    ("시장 수급 분석", r'##\s*시장 수급'),
    ("섹터별 동향", r'##\s*섹터별 동향'),
    ("보유 한국 종목", r'##\s*보유 한국 종목'),
    ("숨은 진주", r'##\s*한국시장 숨은 진주|##\s*숨은 진주'),
    ("5거래일 전망", r'##\s*향후 5거래일|##.*5거래일 전망'),
]


def validate_report(path: str, report_type: str = 'us') -> dict:
    """보고서 검증.

    Returns:
        {
            "file": "2026-02-15_0059.md",
            "passed": True/False,
            "score": 85,  # 0~100
            "issues": [
                {"severity": "error", "message": "섹션 누락: 5거래일 전망"},
                {"severity": "warning", "message": "TSLA 분석 누락"},
            ]
        }
    """
    path = Path(path)
    if not path.exists():
        return {"file": str(path), "passed": False, "score": 0,
                "issues": [{"severity": "error", "message": f"파일 없음: {path}"}]}

    text = path.read_text(encoding='utf-8')
    issues = []
    max_score = 0
    earned_score = 0

    # ── 1) 필수 섹션 체크 ──
    sections = US_REQUIRED_SECTIONS if report_type == 'us' else KR_REQUIRED_SECTIONS
    for name, pattern in sections:
        max_score += 5
        if re.search(pattern, text):
            earned_score += 5
        else:
            issues.append({"severity": "error", "message": f"섹션 누락: {name}"})

    # ── 2) 종목 커버리지 체크 ──
    tickers = TICKERS_US if report_type == 'us' else TICKERS_KR
    covered = 0
    for ticker in tickers:
        max_score += 3
        if ticker in text:
            earned_score += 3
            covered += 1
        else:
            issues.append({"severity": "warning",
                           "message": f"종목 미언급: {ticker}"})

    coverage_pct = round(covered / len(tickers) * 100) if tickers else 0

    # ── 3) 숫자 데이터 밀도 체크 ──
    max_score += 10
    price_pattern = r'[$₩€¥]\s*[\d,]+\.?\d*'
    price_count = len(re.findall(price_pattern, text))
    if price_count >= 50:
        earned_score += 10
    elif price_count >= 30:
        earned_score += 7
    elif price_count >= 15:
        earned_score += 4
    else:
        issues.append({"severity": "warning",
                       "message": f"가격 데이터 부족: {price_count}개 (최소 30개 권장)"})

    # ── 4) 5일 예측 테이블 체크 ──
    max_score += 10
    pred_table = re.search(r'\|\s*종목\s*\|.*예상.*종가', text)
    if pred_table:
        # 예측 행 수 확인
        table_start = pred_table.start()
        table_text = text[table_start:table_start + 3000]
        pred_rows = re.findall(r'\|\s*[A-Z\d]', table_text)
        expected_min = 10 if report_type == 'us' else 3
        if len(pred_rows) >= expected_min:
            earned_score += 10
        else:
            earned_score += 5
            issues.append({"severity": "warning",
                           "message": f"5일 예측 테이블 행 부족: {len(pred_rows)}행 (최소 {expected_min})"})
    else:
        issues.append({"severity": "error", "message": "5일 예측 테이블 없음"})

    # ── 5) 종합 점수 테이블 체크 ──
    max_score += 5
    score_pattern = r'기술[+-]?\s*[+-]?\d+\.?\d*\s*/\s*펀더'
    if re.search(score_pattern, text):
        earned_score += 5
    else:
        issues.append({"severity": "warning", "message": "종합 점수 테이블 미발견"})

    # ── 6) 보고서 길이 체크 ──
    max_score += 5
    word_count = len(text)
    min_length = 30000 if report_type == 'us' else 15000
    if word_count >= min_length:
        earned_score += 5
    else:
        issues.append({"severity": "warning",
                       "message": f"보고서 짧음: {word_count:,}자 (최소 {min_length:,}자 권장)"})

    # ── 7) 예측 회고 체크 (US만) ──
    if report_type == 'us':
        max_score += 5
        if re.search(r'##\s*예측 회고', text):
            earned_score += 5
        else:
            issues.append({"severity": "warning", "message": "예측 회고 섹션 누락"})

    # 최종 점수
    score = round(earned_score / max_score * 100) if max_score > 0 else 0
    errors = sum(1 for i in issues if i['severity'] == 'error')
    passed = errors == 0 and score >= 60

    return {
        "file": path.name,
        "passed": passed,
        "score": score,
        "coverage_pct": coverage_pct,
        "price_count": price_count,
        "word_count": word_count,
        "issues": issues,
    }


def format_result(result: dict) -> str:
    """검증 결과 포맷팅."""
    status = "PASS" if result['passed'] else "FAIL"
    lines = [
        f"[보고서 검증] {result['file']} — {status} ({result['score']}점)",
        f"  종목 커버리지: {result.get('coverage_pct', 0)}% | "
        f"가격 데이터: {result.get('price_count', 0)}개 | "
        f"길이: {result.get('word_count', 0):,}자",
    ]

    errors = [i for i in result['issues'] if i['severity'] == 'error']
    warnings = [i for i in result['issues'] if i['severity'] == 'warning']

    if errors:
        lines.append(f"  오류 ({len(errors)}건):")
        for e in errors:
            lines.append(f"    ✗ {e['message']}")
    if warnings:
        lines.append(f"  경고 ({len(warnings)}건):")
        for w in warnings[:5]:  # 최대 5건
            lines.append(f"    △ {w['message']}")
        if len(warnings) > 5:
            lines.append(f"    ... 외 {len(warnings)-5}건")

    return '\n'.join(lines)


def send_telegram_alert(result: dict):
    """검증 실패 시 텔레그램 경고."""
    from dotenv import load_dotenv
    env_file = STOCK_DIR / ".env"
    if env_file.exists():
        # 수동 로드 (.env 파싱)
        for line in env_file.read_text().strip().split('\n'):
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip()

    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        print("[WARN] 텔레그램 설정 없음", file=sys.stderr)
        return

    status = "PASS ✅" if result['passed'] else "FAIL ❌"
    errors = [i for i in result['issues'] if i['severity'] == 'error']

    msg = f"📋 보고서 검증: {status}\n"
    msg += f"📄 {result['file']} ({result['score']}점)\n"
    if errors:
        msg += f"⚠️ 오류 {len(errors)}건:\n"
        for e in errors[:3]:
            msg += f"  • {e['message']}\n"

    import urllib.request
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": msg}).encode('utf-8')
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[WARN] 텔레그램 전송 실패: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='보고서 품질 검증')
    parser.add_argument('report', help='보고서 파일 경로')
    parser.add_argument('--notify', action='store_true',
                        help='실패 시 텔레그램 경고')
    parser.add_argument('--type', choices=['us', 'kr'], default='us',
                        help='보고서 유형 (us/kr)')
    args = parser.parse_args()

    result = validate_report(args.report, args.type)
    print(format_result(result))

    if args.notify and not result['passed']:
        send_telegram_alert(result)

    sys.exit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
