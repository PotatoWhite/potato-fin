#!/usr/bin/env python3
"""
투자 테제 관리 시스템 (Persistent Investment Thesis)

보고서에서 예측/판단을 추출하고, 실제 가격과 비교해 정확도를 추적하며,
누적 투자 의견(thesis)을 유지한다.

Usage:
    python3 update_thesis.py --init          # 기존 보고서로 초기 테제 빌드
    python3 update_thesis.py --summary       # 현재 테제 요약 출력
    python3 update_thesis.py --report PATH   # 보고서 후 테제 업데이트
    python3 update_thesis.py --weekly        # 주간 회고 (5일 예측 정산)
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────
STOCK_DIR = Path(__file__).resolve().parent
THESIS_FILE = STOCK_DIR / "investment_thesis.json"
REPORT_DIR = STOCK_DIR / "보고서"
KR_REPORT_DIR = REPORT_DIR / "한국"
KST = timezone(timedelta(hours=9))

# 보유 종목 (US + KR + JP + EU)
TICKERS_US = ["NVDA", "MSFT", "GOOGL", "TSLA", "PLTR", "CVX", "XOM",
              "UNH", "WRB", "QCOM", "BOTZ", "SLV"]
TICKERS_KR = ["005930.KS", "000660.KS", "035420.KS", "195940.KQ", "429760.KS"]
TICKERS_JP = ["1377.T"]
TICKERS_EU = ["BAYN.DE"]
ALL_TICKERS = TICKERS_US + TICKERS_KR + TICKERS_JP + TICKERS_EU

# 티커 → 이름 매핑 (보고서 파싱용)
TICKER_NAMES = {
    "NVDA": "엔비디아", "MSFT": "마이크로소프트", "GOOGL": "알파벳",
    "TSLA": "테슬라", "PLTR": "팔란티어", "CVX": "셰브론",
    "XOM": "엑슨모빌", "UNH": "유나이티드헬스", "WRB": "버클리",
    "QCOM": "퀄컴", "BOTZ": "로보틱스", "SLV": "은",
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스",
    "035420.KS": "NAVER", "195940.KQ": "HK이노엔",
    "429760.KS": "PLUS S&P500", "1377.T": "사카타종묘",
    "BAYN.DE": "바이엘",
}

# ── 가격 파싱 유틸 ─────────────────────────────────────────

def parse_price(text: str) -> float | None:
    """멀티통화 가격 파싱: $178.35, ₩254,000, €45.60, ¥3,825"""
    if not text:
        return None
    text = text.strip()
    # 통화 기호 제거
    text = re.sub(r'^[$€¥₩£]', '', text)
    # 콤마 제거
    text = text.replace(',', '')
    # 숫자만 추출
    m = re.search(r'(\d+\.?\d*)', text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def parse_direction(text: str) -> str:
    """방향성 파싱: 강세/약세/횡보 등"""
    text = text.strip().lower()
    if '강세' in text and '약' not in text:
        return 'bullish'
    if '약세' in text:
        return 'bearish'
    if '횡보' in text or '중립' in text:
        return 'neutral'
    if '약한 강세' in text:
        return 'mild_bullish'
    if '약한 약세' in text:
        return 'mild_bearish'
    return 'neutral'


# ── 보고서 파싱 ────────────────────────────────────────────

def parse_report(path: str | Path) -> dict:
    """보고서 마크다운에서 5일 예측 테이블 + 종목별 판단/점수/예측 추출.

    Returns:
        {
            "file": "2026-02-15_0059.md",
            "date": "2026-02-15",
            "predictions_5d": {
                "NVDA": {"current": 178, "est_close": 180, "low": 170, "high": 186,
                         "stop": 168.81, "target": 184.41, "direction": "neutral"},
                ...
            },
            "ticker_analysis": {
                "NVDA": {"judgment": "hold", "scores": {...}, "direction": "bullish",
                         "pred_5d": 180, "pred_mid": [170, 195], "pred_long": 220,
                         "stop_loss": 168.81, "target": 184.41,
                         "special_labels": [], "catalyst": "2/25 실적"},
                ...
            },
            "macro_stance": "cautious_bullish",
            "scenarios": {"A": 25, "B": 40, "C": 25, "D": 10},
        }
    """
    path = Path(path)
    if not path.exists():
        return {}

    text = path.read_text(encoding='utf-8')
    filename = path.name
    date_match = re.match(r'(\d{4}-\d{2}-\d{2})', filename)
    report_date = date_match.group(1) if date_match else ""

    result = {
        "file": filename,
        "date": report_date,
        "predictions_5d": {},
        "ticker_analysis": {},
        "macro_stance": "",
        "scenarios": {},
    }

    # ── 1) 5거래일 예상 범위 테이블 파싱 ──
    _parse_5d_table(text, result)

    # ── 2) 종목별 대응 전략 섹션 파싱 ──
    _parse_ticker_sections(text, result)

    # ── 3) 매크로 스탠스 추출 ──
    _parse_macro(text, result)

    # ── 4) 시나리오 확률 추출 ──
    _parse_scenarios(text, result)

    return result


def _parse_5d_table(text: str, result: dict):
    """종목별 5거래일 예상 범위 테이블 파싱."""
    # 테이블 헤더 패턴: | 종목 | 현재가 | ... | 5일후 예상 종가 | ...
    lines = text.split('\n')
    in_table = False
    header_cols = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith('|'):
            if in_table:
                break  # 테이블 종료
            continue

        cells = [c.strip() for c in stripped.split('|')]
        # 앞뒤 빈 셀 제거
        if cells and cells[0] == '':
            cells = cells[1:]
        if cells and cells[-1] == '':
            cells = cells[:-1]

        if not in_table:
            # 헤더 감지: '종목'과 '예상 종가' 둘 다 포함
            header_text = ''.join(cells)
            if '종목' in header_text and ('예상' in header_text and '종가' in header_text):
                header_cols = cells
                in_table = True
            continue

        # 구분선 건너뛰기
        if all(set(c) <= {'-', ':', ' '} for c in cells if c):
            continue

        # 데이터 행 파싱
        if len(cells) < 5:
            continue

        ticker = cells[0].strip()
        # 티커 정규화 (이름만 있는 경우 변환)
        ticker = _normalize_ticker(ticker)
        if not ticker:
            continue

        row = {}
        for j, col_name in enumerate(header_cols):
            if j < len(cells):
                row[col_name] = cells[j]

        pred = {}
        pred['current'] = parse_price(row.get('현재가', ''))
        pred['est_close'] = parse_price(row.get('5일후 예상 종가', row.get('예상 종가', '')))
        pred['low'] = parse_price(row.get('5일 예상 저가', ''))
        pred['high'] = parse_price(row.get('5일 예상 고가', ''))
        pred['stop'] = parse_price(row.get('손절선', ''))
        pred['target'] = parse_price(row.get('목표가', ''))
        pred['direction'] = parse_direction(row.get('방향성', ''))

        if pred['est_close'] is not None:
            result['predictions_5d'][ticker] = pred


def _parse_ticker_sections(text: str, result: dict):
    """### 종목명 (티커) 섹션에서 판단/점수/예측 추출."""
    # 패턴: ### NVDA (엔비디아) 또는 ### 엔비디아 (NVDA)
    # 또는 ### NAVER (035420.KS) 등
    section_pattern = re.compile(
        r'^###\s+(.+?)(?:\s*[-—]\s*.+)?$',
        re.MULTILINE
    )

    sections = list(section_pattern.finditer(text))
    for idx, match in enumerate(sections):
        section_title = match.group(1).strip()
        ticker = _extract_ticker_from_title(section_title)
        if not ticker:
            continue

        # 섹션 본문: 현재 매치 ~ 다음 ### 또는 ## 까지
        start = match.end()
        if idx + 1 < len(sections):
            end = sections[idx + 1].start()
        else:
            # 다음 ## 헤더까지
            next_h2 = re.search(r'^##\s+', text[start:], re.MULTILINE)
            end = start + next_h2.start() if next_h2 else len(text)

        section_text = text[start:end]
        analysis = _parse_analysis_table(section_text, ticker)
        if analysis:
            result['ticker_analysis'][ticker] = analysis


def _parse_analysis_table(section_text: str, ticker: str) -> dict:
    """종목 분석 테이블에서 주요 필드 추출."""
    analysis = {
        'judgment': '',
        'scores': {},
        'direction': '',
        'pred_5d': None,
        'pred_mid': [],
        'pred_long': None,
        'stop_loss': None,
        'target': None,
        'special_labels': [],
        'catalyst': '',
    }

    lines = section_text.split('\n')
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith('|'):
            continue

        cells = [c.strip() for c in stripped.split('|')]
        if len(cells) < 3:
            continue

        # | 항목 | 내용 | 형태에서 추출
        key = cells[1].strip() if len(cells) > 1 else ''
        val = cells[2].strip() if len(cells) > 2 else ''

        # 판단
        if key == '판단':
            analysis['judgment'] = _parse_judgment(val)

        # 종합 점수: 기술+1.2 / 펀더+4.2 / 수급+0.0 / 센티-0.1 = 종합 +1.7 (매수)
        elif '종합 점수' in key or '종합점수' in key:
            analysis['scores'] = _parse_scores(val)

        # 단기 예측 (5거래일)
        elif '단기' in key and ('5거래일' in key or '5일' in key):
            analysis['pred_5d'] = parse_price(val)
            # 방향 추출
            if '강세' in val:
                analysis['direction'] = 'bullish'
            elif '약세' in val:
                analysis['direction'] = 'bearish'
            elif '횡보' in val:
                analysis['direction'] = 'neutral'

        # 중기 (1~3개월)
        elif '중기' in key:
            prices = re.findall(r'[$₩€¥]\s*[\d,.]+', val)
            analysis['pred_mid'] = [parse_price(p) for p in prices[:2]]

        # 장기 (6~12개월 또는 6개월~1년)
        elif '장기' in key:
            analysis['pred_long'] = parse_price(val)

        # 손절선
        elif key == '손절선':
            analysis['stop_loss'] = parse_price(val)

        # 목표가
        elif key == '목표가':
            analysis['target'] = parse_price(val)

        # 종합 진단 → 특수 라벨
        elif '종합 진단' in key:
            if '셰이크아웃' in val:
                analysis['special_labels'].append('shakeout')
            if '분배' in val:
                analysis['special_labels'].append('distribution')
            if '성장함정' in val:
                analysis['special_labels'].append('growth_trap')

    # 종합 점수에서 방향 보정
    total = analysis['scores'].get('total', 0)
    if not analysis['direction']:
        if total > 1:
            analysis['direction'] = 'bullish'
        elif total < -1:
            analysis['direction'] = 'bearish'
        else:
            analysis['direction'] = 'neutral'

    return analysis


def _parse_judgment(val: str) -> str:
    """판단 텍스트 → 표준 레이블."""
    val_lower = val.lower()
    if '매수' in val_lower and '금지' not in val_lower:
        return 'buy'
    if '매도' in val_lower:
        return 'sell'
    if '관망' in val_lower:
        return 'watch'
    if '보유' in val_lower or '홀드' in val_lower or 'hold' in val_lower:
        return 'hold'
    return 'hold'


def _parse_scores(val: str) -> dict:
    """종합 점수 문자열 파싱.

    Input: "기술+1.2 / 펀더+4.2 / 수급+0.0 / 센티-0.1 = **종합 +1.7 (매수)**"
    Output: {"tech": 1.2, "fund": 4.2, "supply": 0.0, "sent": -0.1, "total": 1.7}
    """
    scores = {}
    # 기술 점수
    m = re.search(r'기술\s*([+-]?\d+\.?\d*)', val)
    if m:
        scores['tech'] = float(m.group(1))
    # 펀더멘탈
    m = re.search(r'펀더\s*([+-]?\d+\.?\d*)', val)
    if m:
        scores['fund'] = float(m.group(1))
    # 수급
    m = re.search(r'수급\s*([+-]?\d+\.?\d*)', val)
    if m:
        scores['supply'] = float(m.group(1))
    # 센티먼트
    m = re.search(r'센티\s*([+-]?\d+\.?\d*)', val)
    if m:
        scores['sent'] = float(m.group(1))
    # 종합
    m = re.search(r'종합\s*([+-]?\d+\.?\d*)', val)
    if m:
        scores['total'] = float(m.group(1))

    return scores


def _parse_macro(text: str, result: dict):
    """매크로 스탠스 추출.

    여러 섹션에서 단서를 수집하여 종합 판단:
    - 매크로 환경 요약
    - 시나리오 확률 (A 강세 > C 약세 → bullish)
    - 핵심 이벤트 요약
    """
    stance_signals = []

    # 1) 매크로 환경 요약 섹션
    m = re.search(r'##\s*매크로 환경 요약\s*\n([\s\S]*?)(?=\n##\s)', text)
    if m:
        macro_text = m.group(1).lower()
        bullish_kw = ['상승', '강세', '호조', '개선', '완화', '인하', '반등',
                      '긍정', '연착륙', '골디락스']
        bearish_kw = ['하락', '약세', '위축', '악화', '긴축', '인상', '침체',
                      '부정', '스태그', '경착륙']
        cautious_kw = ['경계', '조심', '신중', '혼조', '불확실', '관망',
                       '대기', '변동성', '양면']
        b_count = sum(1 for kw in bullish_kw if kw in macro_text)
        br_count = sum(1 for kw in bearish_kw if kw in macro_text)
        c_count = sum(1 for kw in cautious_kw if kw in macro_text)

        if c_count >= 2:
            stance_signals.append('cautious')
        if b_count > br_count + 1:
            stance_signals.append('bullish')
        elif br_count > b_count + 1:
            stance_signals.append('bearish')
        elif b_count > br_count:
            stance_signals.append('mild_bullish')
        elif br_count > b_count:
            stance_signals.append('mild_bearish')

    # 2) 시나리오 확률에서 추론
    scenarios = result.get('scenarios', {})
    if scenarios:
        bull_prob = scenarios.get('A', 0)
        bear_prob = scenarios.get('C', 0) + scenarios.get('D', 0)
        if bull_prob > bear_prob + 15:
            stance_signals.append('bullish')
        elif bear_prob > bull_prob + 15:
            stance_signals.append('bearish')
        else:
            stance_signals.append('neutral')

    # 종합 판단
    if not stance_signals:
        result['macro_stance'] = 'neutral'
        return

    if 'cautious' in stance_signals:
        if 'bullish' in stance_signals or 'mild_bullish' in stance_signals:
            result['macro_stance'] = 'cautious_bullish'
        elif 'bearish' in stance_signals or 'mild_bearish' in stance_signals:
            result['macro_stance'] = 'cautious_bearish'
        else:
            result['macro_stance'] = 'cautious_bullish'
    elif stance_signals.count('bullish') > stance_signals.count('bearish'):
        result['macro_stance'] = 'bullish'
    elif stance_signals.count('bearish') > stance_signals.count('bullish'):
        result['macro_stance'] = 'bearish'
    elif 'mild_bullish' in stance_signals:
        result['macro_stance'] = 'cautious_bullish'
    elif 'mild_bearish' in stance_signals:
        result['macro_stance'] = 'cautious_bearish'
    else:
        result['macro_stance'] = 'neutral'


def _parse_scenarios(text: str, result: dict):
    """시나리오 확률 추출: 경로 A (강세 25%), 경로 B (횡보 40%) 등."""
    for letter in ['A', 'B', 'C', 'D']:
        m = re.search(rf'\*\*경로\s*{letter}\s*\(.*?(\d+)\s*%\s*\)', text)
        if m:
            result['scenarios'][letter] = int(m.group(1))


def _normalize_ticker(name: str) -> str:
    """종목명/티커 정규화."""
    name = name.strip()
    # 이미 티커 형태
    if name in ALL_TICKERS:
        return name
    # TICKER (이름) 형태
    m = re.match(r'^(\S+)\s*\(', name)
    if m and m.group(1) in ALL_TICKERS:
        return m.group(1)
    # 이름 (TICKER) 형태
    m = re.search(r'\((\S+)\)', name)
    if m and m.group(1) in ALL_TICKERS:
        return m.group(1)
    # 이름으로 찾기
    for ticker, kr_name in TICKER_NAMES.items():
        if kr_name in name or name in kr_name:
            return ticker
    # 상위 매칭 (NVDA, MSFT 등 영문 티커)
    for t in ALL_TICKERS:
        base = t.split('.')[0]
        if base == name.upper():
            return t
    return ''


def _extract_ticker_from_title(title: str) -> str:
    """### 섹션 제목에서 티커 추출.

    Examples:
        "NVDA (엔비디아)" → "NVDA"
        "엔비디아 (NVDA)" → "NVDA"
        "NAVER (035420.KS)" → "035420.KS"
    """
    # 괄호 안 티커
    m = re.search(r'\(([^)]+)\)', title)
    if m:
        inner = m.group(1).strip()
        norm = _normalize_ticker(inner)
        if norm:
            return norm

    # 괄호 앞 티커
    parts = re.split(r'\s*[\(（]', title)
    if parts:
        norm = _normalize_ticker(parts[0].strip())
        if norm:
            return norm

    return _normalize_ticker(title)


# ── yfinance 가격 조회 ─────────────────────────────────────

def fetch_actual_prices(tickers: list[str]) -> dict[str, float]:
    """yfinance로 현재가(직전 종가) 조회."""
    import yfinance as yf

    prices = {}
    if not tickers:
        return prices

    try:
        data = yf.download(tickers, period="5d", progress=False, group_by="ticker")
    except Exception as e:
        print(f"[WARN] yfinance download failed: {e}", file=sys.stderr)
        return prices

    for ticker in tickers:
        try:
            if len(tickers) == 1:
                col = data
            else:
                col = data[ticker]
            close = col['Close'].dropna()
            if not close.empty:
                prices[ticker] = round(float(close.iloc[-1]), 2)
        except Exception:
            continue

    return prices


# ── 예측 비교 & 확신도 업데이트 ────────────────────────────

def compare_predictions(thesis: dict, actuals: dict) -> list[dict]:
    """이전 예측 vs 실제 비교, 방향/오차 계산.

    Returns list of comparison results:
        [{"ticker": "NVDA", "predicted": 180, "actual": 182, "error_pct": 1.1,
          "direction_correct": True, "predicted_dir": "bullish", "actual_dir": "up"}, ...]
    """
    results = []
    tickers_data = thesis.get('tickers', {})

    for ticker, tdata in tickers_data.items():
        preds = tdata.get('predictions', {})
        five_d = preds.get('5d', {})
        pred_price = five_d.get('price')
        pred_date = five_d.get('date')
        pred_dir = tdata.get('direction', 'neutral')

        if pred_price is None or ticker not in actuals:
            continue

        actual = actuals[ticker]
        current_at_pred = five_d.get('current')
        if current_at_pred is None:
            continue

        error = actual - pred_price
        error_pct = abs(error / pred_price * 100) if pred_price else 0

        # 방향 판정
        actual_move = actual - current_at_pred
        predicted_move = pred_price - current_at_pred

        if abs(actual_move) < current_at_pred * 0.005:
            actual_dir = 'flat'
        elif actual_move > 0:
            actual_dir = 'up'
        else:
            actual_dir = 'down'

        dir_correct = False
        if pred_dir in ('bullish', 'mild_bullish') and actual_dir == 'up':
            dir_correct = True
        elif pred_dir in ('bearish', 'mild_bearish') and actual_dir == 'down':
            dir_correct = True
        elif pred_dir == 'neutral' and actual_dir == 'flat':
            dir_correct = True
        elif pred_dir == 'neutral':
            dir_correct = True  # 횡보 예측은 관대하게

        results.append({
            'ticker': ticker,
            'predicted': pred_price,
            'actual': actual,
            'current_at_pred': current_at_pred,
            'error': round(error, 2),
            'error_pct': round(error_pct, 2),
            'direction_correct': dir_correct,
            'predicted_dir': pred_dir,
            'actual_dir': actual_dir,
            'pred_date': pred_date,
        })

    return results


def update_conviction(ticker_data: dict, comparison: dict) -> int:
    """확신도 조정.

    Rules:
        방향 적중 + 오차 <3%: +1
        방향 적중 + 오차 >5%: +0
        방향 오류: -1
        방향 오류 + 오차 >10%: -2
        범위: [1, 10]
    """
    conv = ticker_data.get('conviction', 5)
    error_pct = comparison.get('error_pct', 0)
    dir_correct = comparison.get('direction_correct', False)

    if dir_correct:
        if error_pct < 3:
            conv += 1
        # 3~5%: +0 (적중이지만 오차 있음)
        # >5%: +0
    else:
        if error_pct > 10:
            conv -= 2
        else:
            conv -= 1

    return max(1, min(10, conv))


# ── 테제 빌드/업데이트 ─────────────────────────────────────

def _get_latest_reports_per_day(n_days: int = 5, include_kr: bool = True) -> list[Path]:
    """일별 최신 보고서 N개 선택 (날짜별 마지막 파일, US+KR 통합)."""
    reports = sorted(REPORT_DIR.glob("20*.md"))
    if include_kr and KR_REPORT_DIR.exists():
        reports.extend(sorted(KR_REPORT_DIR.glob("20*.md")))

    if not reports:
        return []

    # 날짜별 그룹핑
    by_date: dict[str, list[Path]] = {}
    for r in reports:
        m = re.match(r'(\d{4}-\d{2}-\d{2})', r.name)
        if m:
            d = m.group(1)
            by_date.setdefault(d, []).append(r)

    # 각 날짜에서 가장 큰 (최신) 파일 — US/KR 중 나중 것
    result = []
    for d in sorted(by_date.keys())[-n_days:]:
        files = sorted(by_date[d], key=lambda p: p.name)
        result.append(files[-1])

    return result


def build_initial_thesis() -> dict:
    """기존 보고서(일별 최신 5개)로 초기 테제 빌드."""
    reports = _get_latest_reports_per_day(5)
    if not reports:
        print("[ERROR] 보고서를 찾을 수 없습니다.", file=sys.stderr)
        return {}

    print(f"[INFO] {len(reports)}개 보고서로 초기 테제 빌드:")
    for r in reports:
        print(f"  - {r.name}")

    # 모든 보고서 파싱
    parsed = [parse_report(r) for r in reports]
    parsed = [p for p in parsed if p]

    if not parsed:
        print("[ERROR] 보고서 파싱 결과가 없습니다.", file=sys.stderr)
        return {}

    # 최신 보고서의 판단을 현재 테제로 사용
    latest = parsed[-1]

    # 실제 가격 조회
    print("[INFO] yfinance 가격 조회 중...")
    actuals = fetch_actual_prices(ALL_TICKERS)
    print(f"[INFO] {len(actuals)}개 종목 가격 조회 완료")

    # 예측 비교: N번째 보고서의 예측을 N+1번째 시점 가격과 비교
    all_comparisons = []
    for i in range(len(parsed) - 1):
        report_preds = parsed[i]
        # 다음 보고서 시점의 가격을 "실제"로 사용
        next_report = parsed[i + 1]
        next_prices = {}
        for ticker, pred in next_report.get('predictions_5d', {}).items():
            if pred.get('current') is not None:
                next_prices[ticker] = pred['current']

        # 이 보고서의 예측을 임시 테제로 변환하여 비교
        temp_thesis = {'tickers': {}}
        for ticker, pred in report_preds.get('predictions_5d', {}).items():
            temp_thesis['tickers'][ticker] = {
                'direction': pred.get('direction', 'neutral'),
                'predictions': {
                    '5d': {
                        'price': pred.get('est_close'),
                        'current': pred.get('current'),
                        'date': '',
                    }
                }
            }

        comparisons = compare_predictions(temp_thesis, next_prices)
        all_comparisons.extend(comparisons)

    # 정확도 집계
    total_preds = len(all_comparisons)
    dir_correct = sum(1 for c in all_comparisons if c['direction_correct'])
    avg_error = (sum(c['error_pct'] for c in all_comparisons) / total_preds
                 if total_preds > 0 else 0)

    # 편향 분석
    bullish_bias = sum(1 for c in all_comparisons
                       if c['predicted_dir'] in ('bullish', 'mild_bullish')
                       and not c['direction_correct'])
    bearish_bias = sum(1 for c in all_comparisons
                       if c['predicted_dir'] in ('bearish', 'mild_bearish')
                       and not c['direction_correct'])
    if bullish_bias > bearish_bias + 2:
        systematic_bias = 'bullish'
    elif bearish_bias > bullish_bias + 2:
        systematic_bias = 'bearish'
    elif bullish_bias > bearish_bias:
        systematic_bias = 'mild_bullish'
    elif bearish_bias > bullish_bias:
        systematic_bias = 'mild_bearish'
    else:
        systematic_bias = 'none'

    # 종목별 정확도
    ticker_accuracy: dict[str, list] = {}
    for c in all_comparisons:
        ticker_accuracy.setdefault(c['ticker'], []).append(c['direction_correct'])

    worst = sorted(ticker_accuracy,
                   key=lambda t: sum(ticker_accuracy[t]) / len(ticker_accuracy[t]))[:3]
    best = sorted(ticker_accuracy,
                  key=lambda t: sum(ticker_accuracy[t]) / len(ticker_accuracy[t]),
                  reverse=True)[:3]

    # 테제 빌드
    now = datetime.now(KST).strftime('%Y-%m-%d %H:%M')
    thesis = {
        '_updated': now,
        '_source': latest['file'],
        'macro': {
            'stance': latest.get('macro_stance', 'neutral'),
            'conviction': 5,
            'key_thesis': '',
            'risk_events': [],
            'last_change': latest.get('date', ''),
            'change_reason': '초기 빌드',
        },
        'tickers': {},
        'accuracy': {
            'total_predictions': total_preds,
            'direction_correct': dir_correct,
            'direction_rate': round(dir_correct / total_preds * 100, 1) if total_preds > 0 else 0,
            'avg_error_pct': round(avg_error, 1),
            'systematic_bias': systematic_bias,
            'worst_tickers': worst,
            'best_tickers': best,
        },
        'revision_log': [],
    }

    # 종목별 테제 (최신 보고서 기준)
    for ticker in ALL_TICKERS:
        analysis = latest.get('ticker_analysis', {}).get(ticker, {})
        pred_5d = latest.get('predictions_5d', {}).get(ticker, {})

        # 확신도 초기화: 정확도 기반
        acc_list = ticker_accuracy.get(ticker, [])
        if acc_list:
            rate = sum(acc_list) / len(acc_list)
            init_conv = max(3, min(7, int(rate * 10)))
        else:
            init_conv = 5

        est_close = pred_5d.get('est_close') or analysis.get('pred_5d')
        current_price = pred_5d.get('current')

        thesis['tickers'][ticker] = {
            'judgment': analysis.get('judgment', 'hold'),
            'conviction': init_conv,
            'direction': analysis.get('direction', pred_5d.get('direction', 'neutral')),
            'scores': analysis.get('scores', {}),
            'stop_loss': analysis.get('stop_loss') or pred_5d.get('stop'),
            'target': analysis.get('target') or pred_5d.get('target'),
            'predictions': {
                '5d': {
                    'price': est_close,
                    'current': current_price,
                    'date': _calc_5d_date(latest.get('date', '')),
                    'from_report': latest['file'],
                }
            },
            'key_catalyst': analysis.get('catalyst', ''),
            'special_labels': analysis.get('special_labels', []),
            'last_change': latest.get('date', ''),
            'change_reason': '초기 빌드',
        }

    return thesis


def _calc_5d_date(report_date: str) -> str:
    """보고서 날짜로부터 5거래일 후 날짜 추정 (주말 제외)."""
    try:
        dt = datetime.strptime(report_date, '%Y-%m-%d')
    except (ValueError, TypeError):
        return ''
    days_added = 0
    while days_added < 5:
        dt += timedelta(days=1)
        if dt.weekday() < 5:  # Mon-Fri
            days_added += 1
    return dt.strftime('%Y-%m-%d')


def update_thesis(report_path: str) -> dict:
    """보고서 후 테제 업데이트.

    1. 기존 테제 로드
    2. 보고서 파싱
    3. 실제 가격 조회 → 이전 예측 비교 → 정확도/확신도 업데이트
    4. 새 예측으로 테제 갱신
    5. 저장
    """
    # 기존 테제 로드
    thesis = load_thesis()
    if not thesis:
        print("[WARN] 기존 테제 없음. --init 먼저 실행하세요.", file=sys.stderr)
        return {}

    # 보고서 파싱
    report = parse_report(report_path)
    if not report:
        print(f"[ERROR] 보고서 파싱 실패: {report_path}", file=sys.stderr)
        return thesis

    print(f"[INFO] 보고서 파싱: {report['file']}")
    print(f"  - 5일 예측: {len(report['predictions_5d'])}개 종목")
    print(f"  - 종목 분석: {len(report['ticker_analysis'])}개 종목")

    # 실제 가격 조회
    actuals = fetch_actual_prices(ALL_TICKERS)

    # 이전 예측 비교
    comparisons = compare_predictions(thesis, actuals)
    if comparisons:
        print(f"[INFO] 예측 비교: {len(comparisons)}건")

        # 확신도 업데이트
        revision_log = thesis.get('revision_log', [])
        for comp in comparisons:
            ticker = comp['ticker']
            if ticker not in thesis.get('tickers', {}):
                continue
            tdata = thesis['tickers'][ticker]
            old_conv = tdata.get('conviction', 5)
            new_conv = update_conviction(tdata, comp)
            if old_conv != new_conv:
                revision_log.append({
                    'date': report.get('date', ''),
                    'ticker': ticker,
                    'field': 'conviction',
                    'old': old_conv,
                    'new': new_conv,
                    'reason': f"예측비교: {'적중' if comp['direction_correct'] else '오류'} "
                              f"({comp['predicted']:.0f}→{comp['actual']:.0f}, "
                              f"오차 {comp['error_pct']:.1f}%)",
                })
            tdata['conviction'] = new_conv

        # 정확도 누적 업데이트
        acc = thesis.get('accuracy', {})
        total = acc.get('total_predictions', 0) + len(comparisons)
        correct = acc.get('direction_correct', 0) + sum(
            1 for c in comparisons if c['direction_correct'])
        acc['total_predictions'] = total
        acc['direction_correct'] = correct
        acc['direction_rate'] = round(correct / total * 100, 1) if total > 0 else 0
        # 이동 평균 오차율
        old_avg = acc.get('avg_error_pct', 0)
        new_errors = [c['error_pct'] for c in comparisons]
        avg_new = sum(new_errors) / len(new_errors) if new_errors else 0
        acc['avg_error_pct'] = round((old_avg * 0.7 + avg_new * 0.3), 1)

        # revision_log 최근 20건만 유지
        thesis['revision_log'] = revision_log[-20:]
        thesis['accuracy'] = acc

    # 새 보고서 데이터로 테제 갱신
    now = datetime.now(KST).strftime('%Y-%m-%d %H:%M')
    thesis['_updated'] = now
    thesis['_source'] = report['file']

    # 매크로 스탠스 업데이트
    if report.get('macro_stance'):
        old_stance = thesis.get('macro', {}).get('stance', '')
        if old_stance != report['macro_stance']:
            thesis.setdefault('revision_log', []).append({
                'date': report.get('date', ''),
                'ticker': 'MACRO',
                'field': 'stance',
                'old': old_stance,
                'new': report['macro_stance'],
                'reason': '보고서 매크로 업데이트',
            })
        thesis.setdefault('macro', {})['stance'] = report['macro_stance']
        thesis['macro']['last_change'] = report.get('date', '')

    # 시나리오
    if report.get('scenarios'):
        thesis['macro']['scenarios'] = report['scenarios']

    # 종목별 업데이트
    revision_log = thesis.get('revision_log', [])
    for ticker in ALL_TICKERS:
        analysis = report.get('ticker_analysis', {}).get(ticker, {})
        pred_5d = report.get('predictions_5d', {}).get(ticker, {})

        if not analysis and not pred_5d:
            continue

        tdata = thesis.setdefault('tickers', {}).setdefault(ticker, {
            'judgment': 'hold', 'conviction': 5, 'direction': 'neutral',
            'scores': {}, 'stop_loss': None, 'target': None,
            'predictions': {}, 'key_catalyst': '', 'special_labels': [],
            'last_change': '', 'change_reason': '',
        })

        # 판단 변경 감지
        if analysis.get('judgment') and analysis['judgment'] != tdata.get('judgment', ''):
            old_j = tdata.get('judgment', '')
            revision_log.append({
                'date': report.get('date', ''),
                'ticker': ticker,
                'field': 'judgment',
                'old': old_j,
                'new': analysis['judgment'],
                'reason': '보고서 판단 변경',
            })
            tdata['judgment'] = analysis['judgment']
            tdata['conviction'] = 5  # 판단 변경 시 리셋
            tdata['change_reason'] = '판단 변경'
        elif analysis.get('judgment'):
            tdata['judgment'] = analysis['judgment']

        # 점수 업데이트
        if analysis.get('scores'):
            tdata['scores'] = analysis['scores']

        # 방향
        new_dir = analysis.get('direction') or pred_5d.get('direction', '')
        if new_dir:
            tdata['direction'] = new_dir

        # 손절/목표
        if analysis.get('stop_loss') is not None:
            tdata['stop_loss'] = analysis['stop_loss']
        elif pred_5d.get('stop') is not None:
            tdata['stop_loss'] = pred_5d['stop']

        if analysis.get('target') is not None:
            tdata['target'] = analysis['target']
        elif pred_5d.get('target') is not None:
            tdata['target'] = pred_5d['target']

        # 5일 예측 갱신
        est_close = pred_5d.get('est_close') or analysis.get('pred_5d')
        if est_close is not None:
            tdata['predictions'] = {
                '5d': {
                    'price': est_close,
                    'current': pred_5d.get('current') or actuals.get(ticker),
                    'date': _calc_5d_date(report.get('date', '')),
                    'from_report': report['file'],
                }
            }

        # 특수 라벨
        if analysis.get('special_labels'):
            tdata['special_labels'] = analysis['special_labels']

        # 촉매
        if analysis.get('catalyst'):
            tdata['key_catalyst'] = analysis['catalyst']

        tdata['last_change'] = report.get('date', '')

    thesis['revision_log'] = revision_log[-20:]

    # 저장
    save_thesis(thesis)
    print(f"[INFO] 테제 업데이트 완료 → {THESIS_FILE}")

    return thesis


# ── 테제 I/O ───────────────────────────────────────────────

def load_thesis() -> dict:
    """테제 파일 로드."""
    if not THESIS_FILE.exists():
        return {}
    try:
        return json.loads(THESIS_FILE.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}


def save_thesis(thesis: dict):
    """테제 파일 저장."""
    THESIS_FILE.write_text(
        json.dumps(thesis, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )


# ── 요약 출력 ──────────────────────────────────────────────

def format_thesis_summary() -> str:
    """JSON → 구조화된 텍스트 (Claude 프롬프트용, ~1500자).

    Output format:
        [투자 테제 — 2026-02-15]
        매크로: cautious_bullish (확신 6/10) — 핵심 테제
        예측 정확도: 방향 64.7% (34건). 편향: mild_bullish

        종목별 테제:
        NVDA [7/10 보유↔ 강세] +0.7 | 5d→$185 | 2/25 실적
        ...
        최근 변경: PLTR 확신 6→8 (내부자 매도 확인)
    """
    thesis = load_thesis()
    if not thesis:
        return "투자 테제 없음"

    updated = thesis.get('_updated', '?')
    macro = thesis.get('macro', {})
    acc = thesis.get('accuracy', {})

    lines = [f"[투자 테제 — {updated}]"]

    # 매크로
    stance = macro.get('stance', '?')
    m_conv = macro.get('conviction', 5)
    key_thesis = macro.get('key_thesis', '')
    risk_events = macro.get('risk_events', [])
    lines.append(f"매크로: {stance} (확신 {m_conv}/10)"
                 + (f" — {key_thesis}" if key_thesis else ""))
    if risk_events:
        lines.append(f"리스크 이벤트: {', '.join(risk_events)}")

    # 정확도
    total = acc.get('total_predictions', 0)
    rate = acc.get('direction_rate', 0)
    bias = acc.get('systematic_bias', 'none')
    lines.append(f"예측 정확도: 방향 {rate}% ({total}건). 편향: {bias}")
    lines.append("")

    # 종목별
    lines.append("종목별 테제:")
    tickers = thesis.get('tickers', {})

    # 정렬: 확신도 높은 순
    sorted_tickers = sorted(tickers.items(),
                            key=lambda x: x[1].get('conviction', 0),
                            reverse=True)

    for ticker, tdata in sorted_tickers:
        conv = tdata.get('conviction', 5)
        judgment = tdata.get('judgment', '?')
        direction = tdata.get('direction', '?')
        total_score = tdata.get('scores', {}).get('total', 0)
        pred_5d = tdata.get('predictions', {}).get('5d', {}).get('price', '?')
        catalyst = tdata.get('key_catalyst', '')
        labels = tdata.get('special_labels', [])

        # 판단 한글화
        j_kr = {'buy': '매수', 'sell': '매도', 'hold': '보유', 'watch': '관망'}.get(judgment, judgment)
        d_kr = {'bullish': '강세', 'bearish': '약세', 'neutral': '중립',
                'mild_bullish': '약강세', 'mild_bearish': '약약세'}.get(direction, direction)

        # 가격 포맷
        if isinstance(pred_5d, (int, float)):
            # 한국 종목은 원화
            if '.KS' in ticker or '.KQ' in ticker:
                price_str = f"₩{pred_5d:,.0f}"
            elif '.T' in ticker:
                price_str = f"¥{pred_5d:,.0f}"
            elif '.DE' in ticker:
                price_str = f"€{pred_5d:.1f}"
            else:
                price_str = f"${pred_5d:.0f}"
        else:
            price_str = '?'

        label_str = ' ' + ' '.join(labels) if labels else ''
        score_str = f"{total_score:+.1f}" if total_score else "+0.0"

        line = (f"{ticker} [{conv}/10 {j_kr}↔ {d_kr}] {score_str}"
                f"{label_str} | 5d→{price_str}"
                + (f" | {catalyst}" if catalyst else ""))
        lines.append(line)

    # 최근 변경
    rev_log = thesis.get('revision_log', [])
    if rev_log:
        lines.append("")
        lines.append("최근 변경:")
        for entry in rev_log[-3:]:
            t = entry.get('ticker', '?')
            field = entry.get('field', '?')
            old = entry.get('old', '?')
            new = entry.get('new', '?')
            reason = entry.get('reason', '')
            lines.append(f"  {t} {field}: {old}→{new} ({reason})")

    return '\n'.join(lines)


# ── 주간 회고 ──────────────────────────────────────────────

def weekly_retrospective() -> str:
    """주간 회고: 지난주 모든 5일 예측 vs 실제 가격 정산.

    - 일별 최신 보고서 5개의 5d 예측 수집
    - 현재 실제 가격과 비교
    - 종목별 오차 추이 + 편향 분석
    """
    thesis = load_thesis()
    reports = _get_latest_reports_per_day(7)

    if len(reports) < 2:
        return "[WARN] 보고서가 부족합니다 (최소 2개 필요)"

    print(f"[INFO] 주간 회고: {len(reports)}개 보고서 분석")

    # 실제 가격 조회
    actuals = fetch_actual_prices(ALL_TICKERS)

    # 각 보고서의 예측 수집
    all_preds: dict[str, list[dict]] = {}  # ticker → [{date, predicted, actual, ...}]
    for report_path in reports:
        parsed = parse_report(report_path)
        if not parsed:
            continue

        for ticker, pred in parsed.get('predictions_5d', {}).items():
            est = pred.get('est_close')
            current = pred.get('current')
            actual = actuals.get(ticker)
            if est is None or current is None or actual is None:
                continue

            error = actual - est
            error_pct = abs(error / est * 100) if est else 0
            pred_dir = pred.get('direction', 'neutral')

            actual_move = actual - current
            if abs(actual_move) < current * 0.005:
                actual_dir = 'flat'
            elif actual_move > 0:
                actual_dir = 'up'
            else:
                actual_dir = 'down'

            dir_correct = (
                (pred_dir in ('bullish', 'mild_bullish') and actual_dir == 'up') or
                (pred_dir in ('bearish', 'mild_bearish') and actual_dir == 'down') or
                (pred_dir == 'neutral')
            )

            all_preds.setdefault(ticker, []).append({
                'date': parsed['date'],
                'predicted': est,
                'current_at_pred': current,
                'actual': actual,
                'error_pct': round(error_pct, 1),
                'direction_correct': dir_correct,
                'pred_dir': pred_dir,
            })

    # 종목별 오차 추이 테이블 생성
    lines = [
        f"=== 주간 예측 회고 ({datetime.now(KST).strftime('%Y-%m-%d')}) ===",
        "",
        "종목별 오차 추이:",
        f"{'종목':<12} {'날짜별 오차(%)':<40} {'평균':>6} {'방향적중':>8} {'편향':>10}",
        "-" * 80,
    ]

    overall_correct = 0
    overall_total = 0

    for ticker in ALL_TICKERS:
        preds = all_preds.get(ticker, [])
        if not preds:
            continue

        errors = [f"{p['error_pct']:+.1f}" for p in preds[-5:]]
        avg_err = sum(p['error_pct'] for p in preds) / len(preds)
        dir_rate = sum(1 for p in preds if p['direction_correct'])
        bias_vals = [p['actual'] - p['predicted'] for p in preds]
        avg_bias = sum(bias_vals) / len(bias_vals) if bias_vals else 0

        overall_correct += dir_rate
        overall_total += len(preds)

        if avg_bias > 0:
            bias = "약세편향" if avg_bias > preds[0]['actual'] * 0.02 else "약간↓"
        elif avg_bias < 0:
            bias = "강세편향" if abs(avg_bias) > preds[0]['actual'] * 0.02 else "약간↑"
        else:
            bias = "정확"

        lines.append(
            f"{ticker:<12} {' → '.join(errors):<40} {avg_err:>5.1f}% "
            f"{dir_rate}/{len(preds):<6} {bias:>10}"
        )

    lines.append("-" * 80)
    rate = round(overall_correct / overall_total * 100, 1) if overall_total else 0
    lines.append(f"전체: 방향 적중 {overall_correct}/{overall_total} ({rate}%)")
    lines.append("")

    # 교훈 도출
    lines.append("체계적 교훈:")
    for ticker in ALL_TICKERS:
        preds = all_preds.get(ticker, [])
        if len(preds) < 2:
            continue
        errors = [p['error_pct'] for p in preds]
        if errors[-1] > errors[0] + 3:
            lines.append(f"  {ticker}: 오차 악화 추세 ({errors[0]:.1f}%→{errors[-1]:.1f}%) — 예측 범위 확대 필요")
        dir_misses = sum(1 for p in preds if not p['direction_correct'])
        if dir_misses >= len(preds) * 0.6:
            lines.append(f"  {ticker}: 방향 전환 놓침 빈도 높음 — 기술적 지표 가중치 상향 고려")

    # 테제 정확도 업데이트
    if thesis and overall_total > 0:
        thesis.setdefault('accuracy', {})['weekly_direction_rate'] = rate
        thesis['accuracy']['weekly_date'] = datetime.now(KST).strftime('%Y-%m-%d')
        save_thesis(thesis)

    return '\n'.join(lines)


# ── CLI ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='투자 테제 관리 시스템')
    parser.add_argument('--init', action='store_true',
                        help='기존 보고서로 초기 테제 빌드')
    parser.add_argument('--summary', action='store_true',
                        help='현재 테제 요약 출력')
    parser.add_argument('--report', type=str,
                        help='보고서 경로로 테제 업데이트')
    parser.add_argument('--weekly', action='store_true',
                        help='주간 회고 (5일 예측 정산)')
    args = parser.parse_args()

    if args.init:
        thesis = build_initial_thesis()
        if thesis:
            save_thesis(thesis)
            print(f"\n[OK] 초기 테제 저장: {THESIS_FILE}")
            print(f"\n{format_thesis_summary()}")
        else:
            print("[FAIL] 초기 테제 빌드 실패", file=sys.stderr)
            sys.exit(1)

    elif args.summary:
        print(format_thesis_summary())

    elif args.report:
        thesis = update_thesis(args.report)
        if thesis:
            print(f"\n{format_thesis_summary()}")
        else:
            print("[FAIL] 테제 업데이트 실패", file=sys.stderr)
            sys.exit(1)

    elif args.weekly:
        print(weekly_retrospective())

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
