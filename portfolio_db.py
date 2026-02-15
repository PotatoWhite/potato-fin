#!/usr/bin/env python3
"""
포트폴리오 SQLite 데이터베이스 (portfolio.db)

매매기록/스냅샷을 SQLite로 관리하는 공용 모듈.
기존 xlsx(매매기록.xlsx, 주식.xlsx) 대체.

Usage:
    python3 portfolio_db.py --migrate    # xlsx → SQLite 마이그레이션
    python3 portfolio_db.py --verify     # 마이그레이션 검증
    python3 portfolio_db.py --holdings   # 현재 보유 종목 출력
"""

import argparse
import os
import sqlite3
from datetime import datetime
from pathlib import Path

STOCK_DIR = Path(__file__).resolve().parent
DB_PATH = STOCK_DIR / "portfolio.db"
TRADE_FILE = STOCK_DIR / "매매기록.xlsx"
EXCEL_FILE = STOCK_DIR / "주식.xlsx"

# 섹터 분류 (공용)
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

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    name TEXT,
    ticker TEXT NOT NULL,
    currency TEXT DEFAULT 'KRW',
    action TEXT CHECK(action IN ('매수','매도')),
    qty REAL NOT NULL,
    price REAL NOT NULL,
    amount REAL NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    name TEXT,
    category TEXT,
    currency TEXT,
    price REAL,
    qty REAL,
    cost_amount REAL,
    valuation REAL,
    pnl REAL,
    pnl_pct REAL,
    fx_rate REAL,
    cost_krw REAL,
    valuation_krw REAL,
    pnl_krw REAL,
    dividend_yield REAL,
    sector TEXT,
    UNIQUE(timestamp, ticker)
);

CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_snapshots_ticker ON snapshots(ticker);
"""


def get_db(path: Path | str | None = None) -> sqlite3.Connection:
    """DB 연결 반환. 없으면 스키마 자동 생성."""
    p = Path(path) if path else DB_PATH
    exists = p.exists()
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if not exists:
        conn.executescript(SCHEMA_SQL)
    return conn


def load_portfolio(conn: sqlite3.Connection | None = None) -> list[dict]:
    """현재 보유 종목 계산 (매수/매도 반영).

    Returns:
        [{name, ticker, currency, qty, cost}, ...]
    """
    close = conn is None
    if close:
        conn = get_db()

    rows = conn.execute(
        "SELECT name, ticker, currency, action, qty, amount FROM trades ORDER BY date, id"
    ).fetchall()

    holdings = {}
    for r in rows:
        t = r["ticker"]
        if t not in holdings:
            holdings[t] = {
                "name": r["name"],
                "ticker": t,
                "currency": r["currency"],
                "qty": 0,
                "cost": 0.0,
            }
        h = holdings[t]
        if r["action"] == "매수":
            h["qty"] += r["qty"]
            h["cost"] += r["amount"]
        elif r["action"] == "매도":
            if h["qty"] > 0:
                avg = h["cost"] / h["qty"]
                h["qty"] -= r["qty"]
                h["cost"] = round(avg * h["qty"], 2)

    if close:
        conn.close()

    return [h for h in holdings.values() if h["qty"] > 0]


def get_tickers(conn: sqlite3.Connection | None = None) -> dict:
    """보유 종목 티커 → {name, qty} 딕셔너리."""
    portfolio = load_portfolio(conn)
    return {h["ticker"]: {"name": h["name"], "qty": h["qty"]} for h in portfolio}


def get_cost_basis(conn: sqlite3.Connection | None = None) -> dict:
    """종목별 평균 매입단가. Returns {ticker: {qty, avg_cost}}."""
    portfolio = load_portfolio(conn)
    result = {}
    for h in portfolio:
        if h["qty"] > 0:
            result[h["ticker"]] = {
                "qty": h["qty"],
                "avg_cost": h["cost"] / h["qty"],
            }
    return result


def add_trade(
    date: str, name: str, ticker: str, currency: str,
    action: str, qty: float, price: float,
    amount: float | None = None, note: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """매매 기록 추가. Returns: insert id."""
    if amount is None:
        amount = round(qty * price, 2)
    close = conn is None
    if close:
        conn = get_db()
    cur = conn.execute(
        "INSERT INTO trades (date, name, ticker, currency, action, qty, price, amount, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (date, name, ticker, currency, action, qty, price, amount, note),
    )
    conn.commit()
    rid = cur.lastrowid
    if close:
        conn.close()
    return rid


def add_snapshot(timestamp: str, rows: list[dict], conn: sqlite3.Connection | None = None):
    """한 시점의 포트폴리오 스냅샷 저장."""
    close = conn is None
    if close:
        conn = get_db()
    conn.executemany(
        """INSERT OR REPLACE INTO snapshots
        (timestamp, ticker, name, category, currency, price, qty,
         cost_amount, valuation, pnl, pnl_pct, fx_rate,
         cost_krw, valuation_krw, pnl_krw, dividend_yield, sector)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                timestamp, r["ticker"], r.get("name"), r.get("category"),
                r.get("currency"), r.get("price"), r.get("qty"),
                r.get("cost_amount"), r.get("valuation"), r.get("pnl"),
                r.get("pnl_pct"), r.get("fx_rate"),
                r.get("cost_krw"), r.get("valuation_krw"), r.get("pnl_krw"),
                r.get("dividend_yield"), r.get("sector"),
            )
            for r in rows
        ],
    )
    conn.commit()
    if close:
        conn.close()


def get_snapshot_dates(conn: sqlite3.Connection | None = None) -> list[str]:
    """스냅샷 타임스탬프 목록 (오래된 순)."""
    close = conn is None
    if close:
        conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT timestamp FROM snapshots ORDER BY timestamp"
    ).fetchall()
    if close:
        conn.close()
    return [r["timestamp"] for r in rows]


def get_snapshot(timestamp: str, conn: sqlite3.Connection | None = None) -> list[dict]:
    """특정 시점의 스냅샷 조회."""
    close = conn is None
    if close:
        conn = get_db()
    rows = conn.execute(
        "SELECT * FROM snapshots WHERE timestamp = ? ORDER BY valuation_krw DESC",
        (timestamp,),
    ).fetchall()
    if close:
        conn.close()
    return [dict(r) for r in rows]


# ── 마이그레이션 ────────────────────────────────────────────

def migrate_from_xlsx():
    """기존 xlsx → SQLite 마이그레이션."""
    import pandas as pd

    conn = get_db()

    # 1. trades 테이블 마이그레이션
    existing = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    if existing > 0:
        print(f"  trades 테이블에 이미 {existing}건 존재 — 건너뜀")
    else:
        print("  매매기록.xlsx → trades 마이그레이션...")
        df = pd.read_excel(str(TRADE_FILE), sheet_name="매매기록")
        count = 0
        for _, row in df.iterrows():
            date_val = row["날짜"]
            if pd.isna(date_val):
                date_str = "2000-01-01"  # 초기 매수 (날짜 없음)
            elif hasattr(date_val, "strftime"):
                date_str = date_val.strftime("%Y-%m-%d")
            else:
                date_str = str(date_val).split()[0]

            conn.execute(
                "INSERT INTO trades (date, name, ticker, currency, action, qty, price, amount) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    date_str,
                    str(row["종목명"]),
                    str(row["티커"]),
                    str(row["통화"]),
                    str(row["매매구분"]),
                    float(row["수량"]),
                    float(row["단가"]),
                    float(row["금액"]),
                ),
            )
            count += 1
        conn.commit()
        print(f"  ✓ {count}건 trades INSERT 완료")

    # 2. snapshots 테이블 마이그레이션
    existing = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    if existing > 0:
        print(f"  snapshots 테이블에 이미 {existing}건 존재 — 건너뜀")
    else:
        print("  주식.xlsx → snapshots 마이그레이션...")
        xls = pd.ExcelFile(str(EXCEL_FILE))
        total = 0
        for sname in xls.sheet_names:
            if not (len(sname) == 8 or len(sname) == 12):
                continue
            try:
                sdf = pd.read_excel(xls, sheet_name=sname)
            except Exception:
                continue

            if "상품명" in sdf.columns:
                sdf.rename(columns={"상품명": "종목명"}, inplace=True)

            for _, r in sdf.iterrows():
                pnl_pct = r.get("손익률", 0)
                if isinstance(pnl_pct, str):
                    pnl_pct = pnl_pct.replace("%", "").strip()
                    try:
                        pnl_pct = float(pnl_pct)
                    except (ValueError, TypeError):
                        pnl_pct = 0

                def safe_float(v, default=0):
                    if v is None or v == '' or v == '-':
                        return default
                    try:
                        return float(str(v).replace('%', '').replace(',', '').strip())
                    except (ValueError, TypeError):
                        return default

                conn.execute(
                    """INSERT OR IGNORE INTO snapshots
                    (timestamp, ticker, name, category, currency, price, qty,
                     cost_amount, valuation, pnl, pnl_pct, fx_rate,
                     cost_krw, valuation_krw, pnl_krw)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        sname,
                        str(r.get("티커", "")),
                        str(r.get("종목명", "")),
                        str(r.get("구분", "현금")),
                        str(r.get("통화", "")),
                        safe_float(r.get("현재가")),
                        safe_float(r.get("보유수량")),
                        safe_float(r.get("매입금액")),
                        safe_float(r.get("평가금액")),
                        safe_float(r.get("평가손익")),
                        safe_float(pnl_pct),
                        safe_float(r.get("환율"), 1),
                        safe_float(r.get("매입금액(원)")),
                        safe_float(r.get("평가금액(원)")),
                        safe_float(r.get("평가손익(원)")),
                    ),
                )
                total += 1
        conn.commit()
        print(f"  ✓ {total}건 snapshots INSERT 완료 ({len(xls.sheet_names)}개 시트)")

    conn.close()


def verify_migration():
    """마이그레이션 검증: xlsx vs SQLite 결과 비교."""
    import pandas as pd

    print("\n=== 마이그레이션 검증 ===")

    # xlsx 방식으로 로드
    df = pd.read_excel(str(TRADE_FILE), sheet_name="매매기록")
    xlsx_holdings = {}
    for _, row in df.iterrows():
        t = row["티커"]
        if t not in xlsx_holdings:
            xlsx_holdings[t] = {"qty": 0, "cost": 0.0}
        if row["매매구분"] == "매수":
            xlsx_holdings[t]["qty"] += row["수량"]
            xlsx_holdings[t]["cost"] += row["금액"]
        elif row["매매구분"] == "매도":
            h = xlsx_holdings[t]
            if h["qty"] > 0:
                avg = h["cost"] / h["qty"]
                h["qty"] -= row["수량"]
                h["cost"] = round(avg * h["qty"], 2)

    xlsx_active = {t: h for t, h in xlsx_holdings.items() if h["qty"] > 0}

    # SQLite 방식으로 로드
    db_portfolio = load_portfolio()
    db_active = {h["ticker"]: {"qty": h["qty"], "cost": h["cost"]} for h in db_portfolio}

    # 비교
    all_ok = True
    all_tickers = set(xlsx_active.keys()) | set(db_active.keys())
    for t in sorted(all_tickers):
        x = xlsx_active.get(t, {"qty": 0, "cost": 0})
        d = db_active.get(t, {"qty": 0, "cost": 0})
        qty_match = abs(x["qty"] - d["qty"]) < 0.01
        cost_match = abs(x["cost"] - d["cost"]) < 1.0
        status = "OK" if (qty_match and cost_match) else "MISMATCH"
        if status != "OK":
            all_ok = False
        print(f"  {t:15s} xlsx: {x['qty']:>8.1f}주 ₩{x['cost']:>12,.0f} | "
              f"db: {d['qty']:>8.1f}주 ₩{d['cost']:>12,.0f} | {status}")

    # 스냅샷 개수
    conn = get_db()
    snap_count = conn.execute("SELECT COUNT(DISTINCT timestamp) FROM snapshots").fetchone()[0]
    trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()

    print(f"\n  trades: {trade_count}건, snapshots: {snap_count}개 시점")
    print(f"\n  {'✓ 검증 통과' if all_ok else '✗ 불일치 발견'}")
    return all_ok


def print_holdings():
    """현재 보유 종목 출력."""
    portfolio = load_portfolio()
    print(f"\n=== 보유 종목 ({len(portfolio)}개) ===\n")
    for h in sorted(portfolio, key=lambda x: x["cost"], reverse=True):
        avg = h["cost"] / h["qty"] if h["qty"] > 0 else 0
        print(f"  {h['name']:20s} {h['ticker']:12s} {h['currency']:4s} "
              f"{h['qty']:>8.1f}주 × {avg:>12,.2f} = {h['cost']:>14,.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="포트폴리오 DB 관리")
    parser.add_argument("--migrate", action="store_true", help="xlsx → SQLite 마이그레이션")
    parser.add_argument("--verify", action="store_true", help="마이그레이션 검증")
    parser.add_argument("--holdings", action="store_true", help="현재 보유 종목 출력")
    args = parser.parse_args()

    if args.migrate:
        migrate_from_xlsx()
    if args.verify:
        verify_migration()
    if args.holdings:
        print_holdings()
    if not any([args.migrate, args.verify, args.holdings]):
        parser.print_help()
