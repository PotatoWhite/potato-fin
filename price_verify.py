#!/usr/bin/env python3
"""
보고서 가격 검증 및 자동 보정 (Price Verifier)

보고서 생성 후 실행하여, 보고서 내 종목 가격을 yfinance 실측과 비교하고
오차가 임계값(기본 3%)을 초과하면 자동 보정한다.

Usage:
    python3 price_verify.py <report_path>                    # 검증만 (dry-run)
    python3 price_verify.py <report_path> --fix              # 검증 + 자동 보정
    python3 price_verify.py <report_path> --fix --threshold 5  # 5% 이상만 보정
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

STOCK_DIR = Path(__file__).resolve().parent

# ── 티커 매핑 ─────────────────────────────────────────────
# 보고서에서 사용하는 이름 → yfinance 심볼
TICKER_YF = {
    'NVDA': 'NVDA', 'MSFT': 'MSFT', 'GOOGL': 'GOOGL', 'TSLA': 'TSLA',
    'PLTR': 'PLTR', 'CVX': 'CVX', 'XOM': 'XOM', 'UNH': 'UNH',
    'WRB': 'WRB', 'QCOM': 'QCOM', 'BOTZ': 'BOTZ', 'SLV': 'SLV',
    'BAYN.DE': 'BAYN.DE', 'BAYN': 'BAYN.DE',
    '1377.T': '1377.T', '1377': '1377.T',
    '005930.KS': '005930.KS', '005930': '005930.KS', '삼성전자': '005930.KS',
    '000660.KS': '000660.KS', '000660': '000660.KS', 'SK하이닉스': '000660.KS',
    '035420.KS': '035420.KS', '035420': '035420.KS', 'NAVER': '035420.KS',
    '195940.KQ': '195940.KQ', '195940': '195940.KQ', 'HK이노엔': '195940.KQ',
    '429760.KS': '429760.KS', '429760': '429760.KS',
}

# yfinance 심볼 → 통화 기호
CURRENCY = {
    'NVDA': '$', 'MSFT': '$', 'GOOGL': '$', 'TSLA': '$', 'PLTR': '$',
    'CVX': '$', 'XOM': '$', 'UNH': '$', 'WRB': '$', 'QCOM': '$',
    'BOTZ': '$', 'SLV': '$',
    'BAYN.DE': '€', '1377.T': '¥',
    '005930.KS': '₩', '000660.KS': '₩',
    '035420.KS': '₩', '195940.KQ': '₩', '429760.KS': '₩',
}

# yfinance 심볼 → 보고서에서 주로 쓰는 이름 (역매핑)
YF_TO_REPORT = {
    'NVDA': 'NVDA', 'MSFT': 'MSFT', 'GOOGL': 'GOOGL', 'TSLA': 'TSLA',
    'PLTR': 'PLTR', 'CVX': 'CVX', 'XOM': 'XOM', 'UNH': 'UNH',
    'WRB': 'WRB', 'QCOM': 'QCOM', 'BOTZ': 'BOTZ', 'SLV': 'SLV',
    'BAYN.DE': 'BAYN.DE', '1377.T': '1377.T',
    '005930.KS': '삼성전자', '000660.KS': 'SK하이닉스',
    '035420.KS': 'NAVER', '195940.KQ': 'HK이노엔', '429760.KS': '429760.KS',
}

# 매입 단가를 알기 위해 매매기록에서 읽기
def _load_cost_basis() -> dict:
    """매매기록.xlsx에서 종목별 평균 매입단가 로드."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(STOCK_DIR / "매매기록.xlsx", data_only=True)
        ws = wb.active
        holdings = {}  # yf_symbol → {qty, total_cost}
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[0]:
                break
            ticker = str(row[1]).strip() if row[1] else ''
            action = str(row[3]).strip() if row[3] else ''
            qty = float(row[4]) if row[4] else 0
            price = float(row[5]) if row[5] else 0
            yf = TICKER_YF.get(ticker, ticker)
            if yf not in holdings:
                holdings[yf] = {'qty': 0, 'total_cost': 0}
            if '매수' in action:
                holdings[yf]['qty'] += qty
                holdings[yf]['total_cost'] += qty * price
            elif '매도' in action:
                avg = holdings[yf]['total_cost'] / holdings[yf]['qty'] if holdings[yf]['qty'] else 0
                holdings[yf]['qty'] -= qty
                holdings[yf]['total_cost'] -= qty * avg
        result = {}
        for yf, h in holdings.items():
            if h['qty'] > 0:
                result[yf] = {
                    'qty': h['qty'],
                    'avg_cost': h['total_cost'] / h['qty'],
                }
        return result
    except Exception:
        return {}


def fetch_actual_prices() -> dict:
    """yfinance에서 전 종목 최신 종가 조회."""
    import yfinance as yf
    tickers = list(set(CURRENCY.keys()))
    data = yf.download(tickers, period='2d', progress=False, group_by='ticker')
    prices = {}
    for t in tickers:
        try:
            close = data[t]['Close'].dropna()
            if len(close) >= 1:
                prices[t] = float(close.iloc[-1])
        except Exception:
            try:
                close = data['Close'].dropna()
                if hasattr(close, 'columns'):
                    close = close[t].dropna()
                if len(close) >= 1:
                    prices[t] = float(close.iloc[-1])
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

    return corrections


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


def main():
    parser = argparse.ArgumentParser(description='보고서 가격 검증 및 자동 보정')
    parser.add_argument('report', help='보고서 파일 경로')
    parser.add_argument('--fix', action='store_true', help='자동 보정 적용')
    parser.add_argument('--threshold', type=float, default=5.0,
                        help='보정 임계값 (%%, 기본: 5.0)')
    args = parser.parse_args()

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
