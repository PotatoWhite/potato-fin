import pandas as pd
import yfinance as yf
from datetime import datetime
import argparse
import warnings

from portfolio_db import load_portfolio, add_snapshot, get_db, SECTOR
import naver_finance  # Phase C 2026-04-21: 네이버 우선, yfinance fallback

warnings.filterwarnings('ignore')


def fetch_prices(portfolio):
    """현재가 + 환율 조회 — 네이버 우선, yfinance fallback.

    한국 주식: 네이버 chart API (정확, 0분 지연)
    미국/일본: 네이버 polling API (실시간)
    독일 (BAYN.DE): yfinance (네이버 미지원)
    환율: 네이버 marketindex/exchange/*/prices
    """
    prices = {}
    for h in portfolio:
        ticker = h['ticker']
        try:
            price = naver_finance.get_price(ticker)
            if price is not None:
                prices[ticker] = int(price) if price > 100 else round(price, 2)
            else:
                prices[ticker] = None
        except Exception as e:
            print(f"  ⚠ {ticker} 가격 조회 에러: {e}")
            prices[ticker] = None

    # 환율 (네이버 우선) — 1통화 → KRW
    fx_rates = {'KRW': 1.0}
    for key in ['USD', 'JPY', 'EUR']:
        rate = None
        try:
            rate = naver_finance.get_exchange_rate(key)
        except Exception:
            rate = None
        # 네이버 실패 시 yfinance fallback
        if rate is None:
            try:
                d = yf.Ticker(f'{key}KRW=X').history(period='5d')
                if not d.empty:
                    rate = round(float(d['Close'].iloc[-1]), 2)
            except Exception:
                rate = None
        fx_rates[key] = rate

    return prices, fx_rates


def fetch_dividends(portfolio):
    """종목별 최근 12개월 배당금 조회"""
    from dateutil.relativedelta import relativedelta
    one_year_ago = datetime.now() - relativedelta(years=1)

    dividends = {}
    for h in portfolio:
        ticker = h['ticker']
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
    for h in portfolio:
        name, ticker, currency, qty, cost = h['name'], h['ticker'], h['currency'], h['qty'], h['cost']
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


def save_snapshot(df, timestamp):
    """DataFrame → SQLite 스냅샷 저장"""
    rows = []
    for _, r in df.iterrows():
        pnl_pct = r['손익률']
        if isinstance(pnl_pct, str):
            pnl_pct = pnl_pct.replace('%', '').strip()
            try:
                pnl_pct = float(pnl_pct)
            except (ValueError, TypeError):
                pnl_pct = 0

        rows.append({
            'ticker': r['티커'],
            'name': r['종목명'],
            'category': r.get('구분', '현금'),
            'currency': r['통화'],
            'price': r['현재가'],
            'qty': r['보유수량'],
            'cost_amount': r['매입금액'],
            'valuation': r['평가금액'],
            'pnl': r['평가손익'],
            'pnl_pct': pnl_pct,
            'fx_rate': r['환율'],
            'cost_krw': r['매입금액(원)'],
            'valuation_krw': r['평가금액(원)'],
            'pnl_krw': r['평가손익(원)'],
            'sector': SECTOR.get(r['티커'], '기타'),
        })
    add_snapshot(timestamp, rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--xlsx', action='store_true', help='xlsx 파일도 함께 생성')
    args = parser.parse_args()

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

    failed = [h['name'] for h in portfolio if prices.get(h['ticker']) is None]
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

    # 4. 스냅샷 저장 (SQLite)
    print(f"\n4) 시트 '{sheet_name}' 생성 중...")
    df = build_sheet(portfolio, prices, fx_rates)
    save_snapshot(df, sheet_name)
    print(f"   ✓ portfolio.db에 스냅샷 저장 완료")

    # 4-1. xlsx export (선택)
    if args.xlsx:
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        EXCEL_FILE = '주식.xlsx'
        with pd.ExcelWriter(EXCEL_FILE, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
        print(f"   ✓ {EXCEL_FILE}에 시트 추가 완료")

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
