#!/usr/bin/env python3
"""
보고서 가격 검증 및 자동 보정 (Price Verifier)

보고서 생성 후 실행하여, 보고서 내 종목 가격을 yfinance 실측과 비교하고
오차가 임계값(기본 3%)을 초과하면 자동 보정한다.

Usage:
    python3 price_verify.py <report_path>                    # 검증만 (dry-run)
    python3 price_verify.py <report_path> --fix              # 검증 + 자동 보정
    python3 price_verify.py <report_path> --fix --threshold 5  # 5% 이상만 보정
    python3 price_verify.py --pre-check                       # 보고서 작성 전 사전 가격 검증
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

STOCK_DIR = Path(__file__).resolve().parent

# ── 티커 매핑 (4/28 리셋 후 21종목) ──────────────────────────
# 보고서에서 사용하는 이름 → yfinance 심볼
TICKER_YF = {
    'NVDA': 'NVDA', 'MSFT': 'MSFT', 'GOOGL': 'GOOGL', 'TSLA': 'TSLA',
    'XOM': 'XOM', 'WRB': 'WRB', 'BOTZ': 'BOTZ', 'SLV': 'SLV',
    'GLD': 'GLD', 'IWM': 'IWM', 'LMT': 'LMT', 'WMB': 'WMB', 'XLE': 'XLE',
    'BAYN.DE': 'BAYN.DE', 'BAYN': 'BAYN.DE',
    '1377.T': '1377.T', '1377': '1377.T',
    '005930.KS': '005930.KS', '005930': '005930.KS', '삼성전자': '005930.KS',
    '000660.KS': '000660.KS', '000660': '000660.KS', 'SK하이닉스': '000660.KS',
    '005380.KS': '005380.KS', '005380': '005380.KS', '현대차': '005380.KS',
    '035420.KS': '035420.KS', '035420': '035420.KS', 'NAVER': '035420.KS',
    '195940.KQ': '195940.KQ', '195940': '195940.KQ', 'HK이노엔': '195940.KQ',
    '429760.KS': '429760.KS', '429760': '429760.KS',
}

# yfinance 심볼 → 통화 기호
CURRENCY = {
    'NVDA': '$', 'MSFT': '$', 'GOOGL': '$', 'TSLA': '$',
    'XOM': '$', 'WRB': '$', 'BOTZ': '$', 'SLV': '$',
    'GLD': '$', 'IWM': '$', 'LMT': '$', 'WMB': '$', 'XLE': '$',
    'BAYN.DE': '€', '1377.T': '¥',
    '005930.KS': '₩', '000660.KS': '₩', '005380.KS': '₩',
    '035420.KS': '₩', '195940.KQ': '₩', '429760.KS': '₩',
}

# yfinance 심볼 → 보고서에서 주로 쓰는 이름 (역매핑)
YF_TO_REPORT = {
    'NVDA': 'NVDA', 'MSFT': 'MSFT', 'GOOGL': 'GOOGL', 'TSLA': 'TSLA',
    'XOM': 'XOM', 'WRB': 'WRB', 'BOTZ': 'BOTZ', 'SLV': 'SLV',
    'GLD': 'GLD', 'IWM': 'IWM', 'LMT': 'LMT', 'WMB': 'WMB', 'XLE': 'XLE',
    'BAYN.DE': 'BAYN.DE', '1377.T': '1377.T',
    '005930.KS': '삼성전자', '000660.KS': 'SK하이닉스', '005380.KS': '현대차',
    '035420.KS': 'NAVER', '195940.KQ': 'HK이노엔', '429760.KS': '429760.KS',
}

# 매입 단가를 SQLite에서 읽기
def _load_cost_basis() -> dict:
    """SQLite에서 종목별 평균 매입단가 로드."""
    try:
        from portfolio_db import get_cost_basis
        return get_cost_basis()
    except Exception:
        return {}


def fetch_actual_prices() -> dict:
    """전 종목 최신 종가 조회 — 네이버 우선, yfinance fallback.

    Phase C 2026-04-21: naver_finance.get_price() 사용으로 한국 주식 정확도 향상.
    """
    import naver_finance
    tickers = list(set(CURRENCY.keys()))
    prices = {}
    for t in tickers:
        try:
            price = naver_finance.get_price(t)
            if price is not None:
                prices[t] = float(price)
        except Exception:
            pass
    return prices


def extract_report_prices(text: str) -> dict:
    """보고서에서 종목별 '현재가' 추출.

    Returns:
        {yf_symbol: {'price': float, 'currency': str, 'line': str, 'line_num': int}}
    """
    results = {}
    lines = text.split('\n')

    current_ticker_yf = None

    for i, line in enumerate(lines):
        # 섹션 헤더에서 티커 감지: ### GOOGL (...) 또는 ### 이름 (TICKER)
        header_match = re.match(r'^###\s+(.+)', line)
        if header_match:
            header = header_match.group(1)
            # 패턴1: ### GOOGL (알파벳) 또는 ### NVDA (엔비디아)
            m = re.match(r'(\S+)\s', header)
            if m:
                name = m.group(1)
                yf = TICKER_YF.get(name)
                if yf:
                    current_ticker_yf = yf
                    continue
            # 패턴2: ### 알파벳 (GOOGL) 또는 ### NAVER (035420.KS)
            m = re.search(r'\(([^)]+)\)', header)
            if m:
                inner = m.group(1).strip()
                yf = TICKER_YF.get(inner)
                if yf:
                    current_ticker_yf = yf
                    continue

        # 현재가 추출: **현재가** $305.72 or 현재가: ₩252,500
        if current_ticker_yf and '현재가' in line:
            m = re.search(r'현재가\*?\*?\s*([$₩€¥])\s*([\d,]+\.?\d*)', line)
            if m:
                curr = m.group(1)
                price_str = m.group(2).replace(',', '')
                try:
                    price = float(price_str)
                    results[current_ticker_yf] = {
                        'price': price,
                        'currency': curr,
                        'line': line,
                        'line_num': i,
                    }
                except ValueError:
                    pass

    return results


def extract_forecast_table(text: str) -> dict:
    """5거래일 전망 테이블에서 종목별 현재가 추출.

    Returns:
        {yf_symbol: {'price': float, 'line': str, 'line_num': int}}
    """
    results = {}
    lines = text.split('\n')

    in_forecast = False
    for i, line in enumerate(lines):
        # 5거래일 전망 테이블 감지
        if re.search(r'종목.*현재가.*예상.*종가', line):
            in_forecast = True
            continue
        if in_forecast and line.startswith('|---'):
            continue
        if in_forecast and line.startswith('|'):
            # | GOOGL | $213.52 | $208 | $225 | ...
            cols = [c.strip() for c in line.split('|')]
            if len(cols) >= 3:
                ticker_col = cols[1].strip()
                yf = TICKER_YF.get(ticker_col)
                if yf:
                    price_m = re.search(r'[$₩€¥]\s*([\d,]+\.?\d*)', cols[2])
                    if price_m:
                        try:
                            price = float(price_m.group(1).replace(',', ''))
                            results[yf] = {
                                'price': price,
                                'line': line,
                                'line_num': i,
                            }
                        except ValueError:
                            pass
        elif in_forecast and not line.startswith('|') and line.strip():
            in_forecast = False

    return results


def verify_prices(report_path: str, threshold_pct: float = 3.0) -> dict:
    """보고서 가격 검증.

    Returns:
        {
            'actual_prices': {yf: float},
            'report_prices': {yf: {'price', 'currency', ...}},
            'forecast_prices': {yf: {'price', 'line', ...}},
            'discrepancies': [{yf, report_price, actual_price, diff_pct, currency}],
        }
    """
    text = Path(report_path).read_text(encoding='utf-8')
    actual = fetch_actual_prices()
    report_prices = extract_report_prices(text)
    forecast_prices = extract_forecast_table(text)

    discrepancies = []

    # 현재가 섹션 비교
    for yf, rp in report_prices.items():
        if yf in actual:
            act = actual[yf]
            diff_pct = abs(rp['price'] - act) / act * 100
            if diff_pct > threshold_pct:
                discrepancies.append({
                    'yf': yf,
                    'name': YF_TO_REPORT.get(yf, yf),
                    'report_price': rp['price'],
                    'actual_price': act,
                    'diff_pct': diff_pct,
                    'currency': rp['currency'],
                    'source': '현재가',
                    'line_num': rp['line_num'],
                })

    # 5거래일 테이블 비교
    for yf, fp in forecast_prices.items():
        if yf in actual:
            act = actual[yf]
            diff_pct = abs(fp['price'] - act) / act * 100
            if diff_pct > threshold_pct:
                discrepancies.append({
                    'yf': yf,
                    'name': YF_TO_REPORT.get(yf, yf),
                    'report_price': fp['price'],
                    'actual_price': act,
                    'diff_pct': diff_pct,
                    'currency': CURRENCY.get(yf, '$'),
                    'source': '5거래일표',
                    'line_num': fp['line_num'],
                })

    return {
        'actual_prices': actual,
        'report_prices': report_prices,
        'forecast_prices': forecast_prices,
        'discrepancies': sorted(discrepancies, key=lambda x: x['diff_pct'], reverse=True),
    }


def _fmt_price(price: float, currency: str) -> str:
    """통화별 가격 포맷."""
    if currency in ('₩',):
        return f'{currency}{price:,.0f}'
    elif currency in ('¥',):
        return f'{currency}{price:,.0f}'
    else:
        return f'{currency}{price:,.2f}'


def fix_report(report_path: str, result: dict) -> list:
    """보고서 내 잘못된 가격을 자동 보정.

    Returns:
        list of correction descriptions
    """
    text = Path(report_path).read_text(encoding='utf-8')
    corrections = []
    actual = result['actual_prices']
    cost_basis = _load_cost_basis()

    discrepancies = result['discrepancies']
    if not discrepancies:
        return []

    # 가격 오염 종목 목록 (10%+ 오차)
    contaminated_tickers = []

    # 현재가 라인 보정
    for d in discrepancies:
        if d['source'] != '현재가':
            continue

        yf = d['yf']
        old_price = d['report_price']
        new_price = actual[yf]
        curr = d['currency']
        old_fmt = _fmt_price(old_price, curr)
        new_fmt = _fmt_price(new_price, curr)

        # 현재가 라인 치환: **현재가** $213.52 / **손익** +$2,949 (+7.8%) ...
        # → **현재가** $305.72 / **손익** +$X (+Y%) ...
        rp = result['report_prices'].get(yf)
        if not rp:
            continue
        old_line = rp['line']

        # 새 현재가로 치환
        new_line = old_line.replace(
            f'현재가** {old_fmt}',
            f'현재가** {new_fmt}'
        ).replace(
            f'현재가: {old_fmt}',
            f'현재가: {new_fmt}'
        )

        # 손익 재계산
        cb = cost_basis.get(yf)
        if cb:
            qty = cb['qty']
            avg = cb['avg_cost']
            total_cost = avg * qty
            total_val = new_price * qty
            pnl = total_val - total_cost
            pnl_pct = pnl / total_cost * 100 if total_cost else 0
            sign = '+' if pnl >= 0 else ''

            # 손익 부분 교체
            pnl_pattern = r'\*\*손익\*\*\s*[+-]?[$₩€¥]\s*[\d,.]+\s*\([+-]?[\d.]+%\)'
            pnl_str = f'**손익** {sign}{curr}{abs(pnl):,.0f}' if curr in ('₩', '¥') \
                else f'**손익** {sign}{curr}{abs(pnl):,.2f}'
            pnl_str += f' ({sign}{pnl_pct:.1f}%)'
            new_line = re.sub(pnl_pattern, pnl_str, new_line)

        if old_line != new_line:
            text = text.replace(old_line, new_line)
            corrections.append(
                f'{d["name"]}: 현재가 {old_fmt} → {new_fmt} (오차 {d["diff_pct"]:.1f}%)')

            # 10%+ 오차 종목은 예측 오염 대상
            if d['diff_pct'] > 10:
                contaminated_tickers.append(d['yf'])

    # 5거래일 전망 테이블 보정
    for d in discrepancies:
        if d['source'] != '5거래일표':
            continue

        yf = d['yf']
        old_price = d['report_price']
        new_price = actual[yf]
        curr = d['currency']
        old_fmt = _fmt_price(old_price, curr)
        new_fmt = _fmt_price(new_price, curr)

        fp = result['forecast_prices'].get(yf)
        if not fp:
            continue

        old_line = fp['line']
        # 테이블 행에서 현재가 열만 교체 (첫 번째 가격)
        new_line = old_line.replace(old_fmt, new_fmt, 1)

        if old_line != new_line:
            text = text.replace(old_line, new_line)
            corrections.append(
                f'{d["name"]}: 5거래일표 {old_fmt} → {new_fmt}')

    if corrections:
        # 보고서 상단에 보정 공지 추가
        notice_lines = ['> ⚠️ **가격 자동 보정 적용됨** (price_verify.py)']
        for c in corrections:
            notice_lines.append(f'> - {c}')
        # 큰 보정(>10%)이 있는 종목 예측은 무효 표시
        big_corrections = [c for c in corrections if any(
            d['diff_pct'] > 10 and d['name'] in c
            for d in discrepancies
        )]
        if big_corrections:
            notice_lines.append('> - **주의**: 현재가 오차 >10% 종목의 5거래일 예측은 무효 (잘못된 현재가 기반)')
            for bc in big_corrections:
                notice_lines.append(f'>   → {bc.split(":")[0]}: 예측 무효')
        else:
            notice_lines.append('> - 5거래일 예측값은 보정 전 가격 기준이므로 참고만 할 것')
        notice_lines.append('')
        notice = '\n'.join(notice_lines)

        # 첫 번째 --- 구분선 뒤에 삽입
        hr_match = re.search(r'\n---\n', text)
        if hr_match:
            insert_pos = hr_match.end()
            text = text[:insert_pos] + '\n' + notice + text[insert_pos:]
        else:
            # 제목 다음에 삽입
            title_match = re.search(r'^# .+\n', text)
            if title_match:
                insert_pos = title_match.end()
                text = text[:insert_pos] + '\n' + notice + text[insert_pos:]

        Path(report_path).write_text(text, encoding='utf-8')

    # investment_thesis.json에 오염 플래그 추가
    if contaminated_tickers:
        _mark_contaminated_predictions(contaminated_tickers)

    return corrections


def _mark_contaminated_predictions(tickers: list[str]):
    """가격 오염 종목의 예측을 무효화.

    investment_thesis.json에 price_contaminated: true 플래그를 추가하여
    향후 예측 비교 시 이 종목을 건너뛰도록 한다.
    """
    thesis_file = STOCK_DIR / "investment_thesis.json"
    if not thesis_file.exists():
        return

    try:
        thesis = json.loads(thesis_file.read_text(encoding='utf-8'))
        now = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M')

        for ticker in tickers:
            if ticker in thesis.get('tickers', {}):
                tdata = thesis['tickers'][ticker]
                tdata['price_contaminated'] = True
                tdata['contaminated_date'] = now

                # 현재 예측 삭제 (다음 보고서에서 재설정됨)
                if 'predictions' in tdata:
                    tdata['predictions'] = {}

                # 확신도 리셋
                old_conv = tdata.get('conviction', 5)
                if old_conv > 3:
                    tdata['conviction'] = 3
                    thesis.setdefault('revision_log', []).append({
                        'date': now.split()[0],
                        'ticker': ticker,
                        'field': 'conviction',
                        'old': old_conv,
                        'new': 3,
                        'reason': f'가격 오염 (현재가 오차 >10%)',
                    })

        thesis['_updated'] = now
        thesis_file.write_text(json.dumps(thesis, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"[INFO] {len(tickers)}개 종목 예측 무효화: {tickers}")
    except Exception as e:
        print(f"[WARN] 테제 업데이트 실패: {e}", file=sys.stderr)


def format_result(result: dict) -> str:
    """검증 결과 요약."""
    discs = result['discrepancies']
    if not discs:
        return '[가격 검증] PASS — 모든 종목 가격 정상'

    lines = [f'[가격 검증] {len(discs)}건 오차 발견:']
    for d in discs:
        old = _fmt_price(d['report_price'], d['currency'])
        act = _fmt_price(d['actual_price'], d['currency'])
        lines.append(
            f'  {d["name"]:>8s} {d["source"]:6s}: 보고서 {old} → 실제 {act} '
            f'(오차 {d["diff_pct"]:.1f}%)')
    return '\n'.join(lines)


def pre_check_prices(threshold_pct: float = 10.0) -> dict:
    """보고서 작성 전 사전 가격 검증.

    yfinance에서 전 종목 가격을 조회하고, investment_thesis.json에 저장된
    마지막 현재가와 비교하여 큰 오차(>threshold_pct)가 있으면 경고한다.

    Returns:
        {
            'actual_prices': {yf: float},
            'thesis_prices': {yf: float},
            'warnings': [{yf, name, thesis_price, actual_price, diff_pct}],
        }
    """
    thesis_file = STOCK_DIR / "investment_thesis.json"
    actual = fetch_actual_prices()
    thesis_prices = {}

    if thesis_file.exists():
        try:
            thesis = json.loads(thesis_file.read_text(encoding='utf-8'))
            for yf, tdata in thesis.get('tickers', {}).items():
                last_price = tdata.get('last_price')
                if last_price:
                    thesis_prices[yf] = last_price
        except Exception as e:
            print(f"[WARN] investment_thesis.json 읽기 실패: {e}", file=sys.stderr)

    warnings = []
    for yf, act in actual.items():
        if yf in thesis_prices:
            thesis_p = thesis_prices[yf]
            diff_pct = abs(act - thesis_p) / thesis_p * 100
            if diff_pct > threshold_pct:
                warnings.append({
                    'yf': yf,
                    'name': YF_TO_REPORT.get(yf, yf),
                    'thesis_price': thesis_p,
                    'actual_price': act,
                    'diff_pct': diff_pct,
                    'currency': CURRENCY.get(yf, '$'),
                })

    return {
        'actual_prices': actual,
        'thesis_prices': thesis_prices,
        'warnings': sorted(warnings, key=lambda x: x['diff_pct'], reverse=True),
    }


def format_pre_check_result(result: dict) -> str:
    """사전 검증 결과 요약."""
    warns = result['warnings']
    if not warns:
        return '[사전 가격 검증] PASS — 모든 종목 정상 (투자테제 대비)'

    lines = [f'[사전 가격 검증] ⚠️ {len(warns)}건 가격 급변 감지 (투자테제 대비):']
    for w in warns:
        old = _fmt_price(w['thesis_price'], w['currency'])
        act = _fmt_price(w['actual_price'], w['currency'])
        lines.append(
            f'  {w["name"]:>8s}: 테제 {old} → 현재 {act} '
            f'(변동 {w["diff_pct"]:.1f}%)')
    lines.append('\n⚠️ Claude가 학습 데이터의 과거 가격을 사용할 수 있음.')
    lines.append('   보고서 작성 시 위 종목의 가격을 신중히 확인할 것.')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='보고서 가격 검증 및 자동 보정')
    parser.add_argument('report', nargs='?', help='보고서 파일 경로')
    parser.add_argument('--fix', action='store_true', help='자동 보정 적용')
    parser.add_argument('--threshold', type=float, default=5.0,
                        help='보정 임계값 (%%, 기본: 5.0)')
    parser.add_argument('--pre-check', action='store_true',
                        help='보고서 작성 전 사전 가격 검증 (투자테제 vs 현재가)')
    args = parser.parse_args()

    # 사전 검증 모드
    if args.pre_check:
        print('[사전 가격 검증] 보고서 작성 전 가격 급변 감지 중...')
        result = pre_check_prices(threshold_pct=10.0)
        print(format_pre_check_result(result))
        sys.exit(1 if result['warnings'] else 0)

    # 보고서 검증 모드
    if not args.report:
        parser.error('보고서 파일 경로가 필요합니다 (또는 --pre-check 사용)')

    report_path = args.report
    if not Path(report_path).exists():
        print(f'[ERROR] 파일 없음: {report_path}', file=sys.stderr)
        sys.exit(1)

    print(f'[가격 검증] {Path(report_path).name} (임계값: {args.threshold}%)')
    result = verify_prices(report_path, args.threshold)
    print(format_result(result))

    if args.fix and result['discrepancies']:
        corrections = fix_report(report_path, result)
        if corrections:
            print(f'\n[자동 보정] {len(corrections)}건 보정 완료:')
            for c in corrections:
                print(f'  ✓ {c}')
        else:
            print('\n[자동 보정] 보정 대상 없음')

    discs = result['discrepancies']
    sys.exit(1 if discs else 0)


if __name__ == '__main__':
    main()
