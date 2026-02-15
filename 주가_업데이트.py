import pandas as pd
import yfinance as yf
from datetime import datetime
import numpy as np
import warnings
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
from openpyxl.utils import get_column_letter

warnings.filterwarnings('ignore')

# === 색상/스타일 설정 ===
HEADER_FILL = PatternFill('solid', fgColor='1F4E79')
HEADER_FONT = Font(bold=True, color='FFFFFF', size=11)
GAIN_FONT = Font(color='006100')
GAIN_FILL = PatternFill('solid', fgColor='C6EFCE')
LOSS_FONT = Font(color='9C0006')
LOSS_FILL = PatternFill('solid', fgColor='FFC7CE')
EVEN_ROW_FILL = PatternFill('solid', fgColor='F2F7FB')
THIN_BORDER = Border(
    bottom=Side(style='thin', color='D9E2EC'),
)
CENTER = Alignment(horizontal='center', vertical='center')
RIGHT = Alignment(horizontal='right', vertical='center')

EXCEL_FILE = '주식.xlsx'
PIVOT_FILE = '주식_통합.xlsx'
TRADE_FILE = '매매기록.xlsx'

# 섹터 분류
SECTOR = {
    '005930.KS': 'IT',            # 삼성전자
    '000660.KS': 'IT',            # SK하이닉스
    '035420.KS': 'IT',            # NAVER
    '195940.KQ': '헬스케어',       # HK이노엔
    '429760.KS': 'ETF/인덱스',    # PLUS 미국S&P500
    '1377.T':    '소비재',         # 사카타종묘
    'BAYN.DE':   '헬스케어',       # 바이엘
    'BOTZ':      'ETF/테마',      # GLOBAL X ROBOTICS & AI
    'CRWV':      'IT',            # 코어위브
    'CVX':       '에너지',         # 셰브론
    'GOOGL':     'IT',            # 알파벳 A
    'MSFT':      'IT',            # 마이크로소프트
    'NVDA':      'IT',            # 엔비디아
    'PLTR':      'IT',            # 팔란티어
    'QCOM':      'IT',            # 퀄컴
    'SLV':       'ETF/원자재',    # iShares Silver Trust
    'TSLA':      '자동차',         # 테슬라
    'UNH':       '헬스케어',       # 유나이티드헬스
    'WRB':       '금융',           # WR 버클리
    'XOM':       '에너지',         # 엑슨 모빌
}


def load_portfolio():
    """매매기록.xlsx에서 현재 포트폴리오 계산 (매수/매도 반영)"""
    df = pd.read_excel(TRADE_FILE, sheet_name='매매기록')

    holdings = {}
    for _, row in df.iterrows():
        ticker = row['티커']
        if ticker not in holdings:
            holdings[ticker] = {
                '종목명': row['종목명'],
                '티커': ticker,
                '통화': row['통화'],
                '수량': 0,
                '매입금액': 0.0,
            }

        if row['매매구분'] == '매수':
            holdings[ticker]['수량'] += row['수량']
            holdings[ticker]['매입금액'] += row['금액']
        elif row['매매구분'] == '매도':
            # 매도 시 평균단가 기준으로 매입금액 차감
            h = holdings[ticker]
            if h['수량'] > 0:
                avg_cost = h['매입금액'] / h['수량']
                h['수량'] -= row['수량']
                h['매입금액'] = round(avg_cost * h['수량'], 2)

    # 보유수량 > 0인 종목만
    portfolio = []
    for t, h in holdings.items():
        if h['수량'] > 0:
            portfolio.append((h['종목명'], h['티커'], h['통화'], h['수량'], round(h['매입금액'], 2)))

    return portfolio


def fetch_prices(portfolio):
    """yfinance로 현재가 + 환율 조회"""
    tickers = [row[1] for row in portfolio]
    fx_pairs = ['USDKRW=X', 'JPYKRW=X', 'EURKRW=X']
    data = yf.download(tickers + fx_pairs, period='5d', progress=False)

    prices = {}
    for name, ticker, *_ in portfolio:
        try:
            col = data['Close'][ticker].dropna()
            if not col.empty:
                price = float(col.iloc[-1])
                prices[ticker] = int(price) if price > 100 else round(price, 2)
            else:
                prices[ticker] = None
        except Exception:
            prices[ticker] = None

    # 환율 (1통화 → KRW)
    fx_rates = {'KRW': 1.0}
    for pair, key in [('USDKRW=X', 'USD'), ('JPYKRW=X', 'JPY'), ('EURKRW=X', 'EUR')]:
        try:
            col = data['Close'][pair].dropna()
            fx_rates[key] = round(float(col.iloc[-1]), 2) if not col.empty else None
        except Exception:
            fx_rates[key] = None

    return prices, fx_rates


def fetch_dividends(portfolio):
    """종목별 최근 12개월 배당금 조회"""
    from dateutil.relativedelta import relativedelta
    one_year_ago = datetime.now() - relativedelta(years=1)

    dividends = {}
    for name, ticker, *_ in portfolio:
        try:
            tk = yf.Ticker(ticker)
            divs = tk.dividends
            if not divs.empty:
                recent = divs[divs.index >= one_year_ago.strftime('%Y-%m-%d')]
                annual_per_share = round(recent.sum(), 4) if not recent.empty else 0
                last_div = round(divs.iloc[-1], 4)
                last_date = divs.index[-1].strftime('%Y-%m-%d')
            else:
                annual_per_share, last_div, last_date = 0, 0, '-'
        except Exception:
            annual_per_share, last_div, last_date = 0, 0, '-'

        dividends[ticker] = {
            '연간배당(주당)': annual_per_share,
            '최근배당(주당)': last_div,
            '최근배당일': last_date,
        }
    return dividends


def build_sheet(portfolio, prices, fx_rates):
    """포트폴리오 데이터프레임 생성 (원화 환산 포함)"""
    rows = []
    for name, ticker, currency, qty, cost in portfolio:
        price = prices.get(ticker)
        if price is None:
            print(f"  ⚠ {name} ({ticker}) 가격 조회 실패 - 건너뜀")
            continue

        valuation = round(price * qty, 2)
        pnl = round(valuation - cost, 2)
        pnl_pct = round(pnl / cost * 100, 2) if cost != 0 else 0

        rate = fx_rates.get(currency, 1.0)
        cost_krw = round(cost * rate)
        val_krw = round(valuation * rate)
        pnl_krw = val_krw - cost_krw

        rows.append({
            '종목명': name,
            '티커': ticker,
            '구분': '현금',
            '통화': currency,
            '현재가': price,
            '보유수량': qty,
            '매입금액': cost,
            '평가금액': valuation,
            '평가손익': pnl,
            '손익률': f'{pnl_pct} %',
            '환율': rate,
            '매입금액(원)': cost_krw,
            '평가금액(원)': val_krw,
            '평가손익(원)': pnl_krw,
        })
    return pd.DataFrame(rows)


def style_sheet(ws):
    """워크시트에 색상/스타일 적용"""
    # 헤더 스타일
    for cell in ws[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER

    # 손익/손익률 컬럼 인덱스 찾기
    headers = {cell.value: cell.column for cell in ws[1]}
    pnl_cols = [headers.get(h) for h in ['평가손익', '손익률', '평가손익(원)'] if h in headers]

    # 데이터 행 스타일
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, max_row=ws.max_row), start=0):
        # 줄무늬 배경
        if row_idx % 2 == 0:
            for cell in row:
                cell.fill = EVEN_ROW_FILL

        # 테두리
        for cell in row:
            cell.border = THIN_BORDER
            cell.alignment = RIGHT

        # 손익 컬럼 조건부 색상
        for col_idx in pnl_cols:
            if col_idx is None:
                continue
            cell = ws.cell(row=row[0].row, column=col_idx)
            try:
                val = float(str(cell.value).replace('%', '').replace(',', '').strip())
                if val > 0:
                    cell.font = GAIN_FONT
                    cell.fill = GAIN_FILL
                elif val < 0:
                    cell.font = LOSS_FONT
                    cell.fill = LOSS_FILL
            except (ValueError, TypeError):
                pass

    # 열 너비 자동 조정
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val = str(cell.value) if cell.value else ''
            max_len = max(max_len, len(val.encode('utf-8')))
        ws.column_dimensions[col_letter].width = min(max_len * 1.1 + 2, 30)


def add_sheet(df, sheet_name):
    """주식.xlsx에 새 시트 추가 (스타일 포함)"""
    with pd.ExcelWriter(EXCEL_FILE, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        style_sheet(writer.sheets[sheet_name])


def rebuild_pivot():
    """주식_통합.xlsx 피벗 파일 재생성"""
    excel_file = pd.ExcelFile(EXCEL_FILE)
    all_data = []

    for sname in excel_file.sheet_names:
        sdf = pd.read_excel(excel_file, sheet_name=sname)
        try:
            if len(sname) == 8:
                date = datetime.strptime(sname, '%Y%m%d')
            elif len(sname) == 12:
                date = datetime.strptime(sname, '%Y%m%d%H%M')
            else:
                continue
        except Exception:
            continue

        if '상품명' in sdf.columns:
            sdf.rename(columns={'상품명': '종목명'}, inplace=True)
        sdf['날짜'] = date
        all_data.append(sdf)

    combined = pd.concat(all_data, ignore_index=True)
    combined['손익률_num'] = pd.to_numeric(
        combined['손익률'].astype(str).str.replace('%', '').str.strip().replace('-', np.nan),
        errors='coerce'
    )

    metrics = {
        '평가금액': '평가금액',
        '평가손익': '평가손익',
        '손익률': '손익률_num',
    }

    with pd.ExcelWriter(PIVOT_FILE, engine='openpyxl') as writer:
        for sname, col in metrics.items():
            pivot = combined.pivot_table(index='종목명', columns='날짜', values=col, aggfunc='first')
            pivot.columns = [
                d.strftime('%m/%d %H:%M') if d.hour or d.minute else d.strftime('%m/%d')
                for d in pivot.columns
            ]
            pivot.to_excel(writer, sheet_name=sname)
            style_pivot(writer.sheets[sname], is_pct=(sname == '손익률'))

    print(f"  ✓ {PIVOT_FILE} 업데이트 완료")


def style_pivot(ws, is_pct=False):
    """피벗 시트 스타일 적용 (손익 셀에 빨강/초록)"""
    # 헤더 행 (1행: 빈칸 + 날짜들, 2행도 있을 수 있음)
    for cell in ws[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER

    # A열(종목명) 스타일
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=1):
        for cell in row:
            cell.font = Font(bold=True, size=10)
            cell.alignment = Alignment(horizontal='left', vertical='center')

    # 데이터 셀: 조건부 색상 (손익률/손익 시트)
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=2, max_col=ws.max_column):
        for cell in row:
            cell.alignment = RIGHT
            try:
                val = float(cell.value) if cell.value is not None else None
                if val is not None and val > 0:
                    cell.font = GAIN_FONT
                    cell.fill = GAIN_FILL
                elif val is not None and val < 0:
                    cell.font = LOSS_FONT
                    cell.fill = LOSS_FILL
            except (ValueError, TypeError):
                pass

    # 열 너비
    ws.column_dimensions['A'].width = 22
    for col_idx in range(2, ws.max_column + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 14


def main():
    now = datetime.now()
    sheet_name = now.strftime('%Y%m%d%H%M')

    print(f"=== 주가 업데이트 ({now.strftime('%Y-%m-%d %H:%M')}) ===\n")

    # 1. 매매기록에서 포트폴리오 로드
    print("1) 매매기록 로드 중...")
    portfolio = load_portfolio()
    print(f"   {len(portfolio)}개 종목 보유 중")

    # 2. 현재가 + 환율 조회
    print("\n2) 현재가 + 환율 조회 중...")
    prices, fx_rates = fetch_prices(portfolio)

    failed = [name for name, ticker, *_ in portfolio if prices.get(ticker) is None]
    ok = len(portfolio) - len(failed)
    print(f"   {ok}/{len(portfolio)}개 종목 조회 성공")
    if failed:
        print(f"   실패: {', '.join(failed)}")

    fx_display = [f"{k} {v:,.2f}" for k, v in fx_rates.items() if k != 'KRW']
    print(f"   환율: {' | '.join(fx_display)}")

    # 3. 배당 데이터 조회
    print("\n3) 배당 데이터 조회 중...")
    dividends = fetch_dividends(portfolio)
    div_count = sum(1 for v in dividends.values() if v['연간배당(주당)'] > 0)
    print(f"   {div_count}/{len(portfolio)}개 종목 배당 있음")

    # 4. 시트 생성
    print(f"\n4) 시트 '{sheet_name}' 생성 중...")
    df = build_sheet(portfolio, prices, fx_rates)
    add_sheet(df, sheet_name)
    print(f"   ✓ {EXCEL_FILE}에 시트 추가 완료")

    # 5. 통합 피벗 파일 재생성
    print(f"\n5) 통합 파일 재생성 중...")
    rebuild_pivot()

    # 5. 결과 출력
    print(f"\n=== 포트폴리오 현황 ===\n")
    print(df.to_string(index=False))

    # 통화별 합계
    print(f"\n=== 통화별 합계 ===")
    for currency in df['통화'].unique():
        subset = df[df['통화'] == currency]
        total_cost = subset['매입금액'].sum()
        total_val = subset['평가금액'].sum()
        total_pnl = subset['평가손익'].sum()
        pct = round(total_pnl / total_cost * 100, 2) if total_cost else 0
        print(f"  {currency}: 매입 {total_cost:>14,.2f} → 평가 {total_val:>14,.2f} | 손익 {total_pnl:>12,.2f} ({pct}%)")

    # 원화 환산 총합
    total_cost_krw = df['매입금액(원)'].sum()
    total_val_krw = df['평가금액(원)'].sum()
    total_pnl_krw = df['평가손익(원)'].sum()
    total_pct = round(total_pnl_krw / total_cost_krw * 100, 2) if total_cost_krw else 0

    print(f"\n=== 총자산 (원화 환산) ===")
    print(f"  총 매입금액:  {total_cost_krw:>15,} 원")
    print(f"  총 평가금액:  {total_val_krw:>15,} 원")
    print(f"  총 평가손익:  {total_pnl_krw:>15,} 원 ({total_pct}%)")

    # === 비중 분석 ===
    print(f"\n=== 비중 분석 ===")

    # 종목별 비중 (평가금액 원화 기준, 내림차순)
    print(f"\n  [종목별 비중]")
    df_sorted = df.sort_values('평가금액(원)', ascending=False)
    for _, r in df_sorted.iterrows():
        pct = r['평가금액(원)'] / total_val_krw * 100
        bar = '█' * int(pct / 2)
        print(f"  {r['종목명']:20s} {r['평가금액(원)']:>13,}원  {pct:5.1f}%  {bar}")

    # 통화별 비중
    print(f"\n  [통화별 비중]")
    for currency in ['KRW', 'USD', 'JPY', 'EUR']:
        subset = df[df['통화'] == currency]
        if subset.empty:
            continue
        val = subset['평가금액(원)'].sum()
        pct = val / total_val_krw * 100
        bar = '█' * int(pct / 2)
        print(f"  {currency:5s} {val:>13,}원  {pct:5.1f}%  {bar}")

    # 섹터별 비중
    print(f"\n  [섹터별 비중]")
    df['섹터'] = df['티커'].map(SECTOR).fillna('기타')
    sector_group = df.groupby('섹터')['평가금액(원)'].sum().sort_values(ascending=False)
    for sector, val in sector_group.items():
        pct = val / total_val_krw * 100
        bar = '█' * int(pct / 2)
        print(f"  {sector:10s} {val:>13,}원  {pct:5.1f}%  {bar}")

    # === 배당 분석 ===
    print(f"\n=== 배당 분석 (최근 12개월 기준) ===\n")

    div_rows = []
    for _, r in df.iterrows():
        ticker = r['티커']
        d = dividends.get(ticker, {})
        annual_ps = d.get('연간배당(주당)', 0)
        qty = r['보유수량']
        price = r['현재가']
        currency = r['통화']
        rate = fx_rates.get(currency, 1.0)

        annual_total = round(annual_ps * qty, 2)
        annual_total_krw = round(annual_total * rate)
        div_yield = round(annual_ps / price * 100, 2) if price > 0 and annual_ps > 0 else 0

        div_rows.append({
            '종목명': r['종목명'],
            '통화': currency,
            '최근배당일': d.get('최근배당일', '-'),
            '주당배당(연)': annual_ps,
            '보유수량': qty,
            '예상배당금': annual_total,
            '배당수익률': div_yield,
            '예상배당금(원)': annual_total_krw,
        })

    div_df = pd.DataFrame(div_rows)
    # 배당 있는 종목만 표시
    div_active = div_df[div_df['주당배당(연)'] > 0].sort_values('예상배당금(원)', ascending=False)
    div_none = div_df[div_df['주당배당(연)'] == 0]

    if not div_active.empty:
        for _, r in div_active.iterrows():
            print(f"  {r['종목명']:20s} | 수익률 {r['배당수익률']:5.2f}% | "
                  f"주당 {r['주당배당(연)']:>8} {r['통화']} | "
                  f"예상 {r['예상배당금(원)']:>10,}원/년 | 최근 {r['최근배당일']}")

    if not div_none.empty:
        names = ', '.join(div_none['종목명'].tolist())
        print(f"\n  배당 없음: {names}")

    total_div_krw = div_df['예상배당금(원)'].sum()
    div_yield_total = round(total_div_krw / total_val_krw * 100, 2) if total_val_krw > 0 else 0

    print(f"\n  예상 연간 배당금 합계:  {total_div_krw:>10,} 원")
    print(f"  예상 월평균 배당금:    {total_div_krw // 12:>10,} 원")
    print(f"  포트폴리오 배당수익률:      {div_yield_total}%")


if __name__ == '__main__':
    main()
