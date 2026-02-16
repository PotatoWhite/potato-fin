#!/usr/bin/env python3
"""
비서 SQLite 데이터베이스 (assistant.db)

메모/할일/리마인더/대화 로그를 관리하는 모듈.
portfolio_db.py 패턴을 따른다.

Usage:
    python3 assistant_db.py --init     # DB 초기화
    python3 assistant_db.py --stats    # 통계 출력
"""

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

STOCK_DIR = Path(__file__).resolve().parent
DB_PATH = STOCK_DIR / "assistant.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memos (
    id INTEGER PRIMARY KEY,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    category TEXT DEFAULT 'general',
    content TEXT NOT NULL,
    tags TEXT,
    pinned INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    content TEXT NOT NULL,
    priority TEXT DEFAULT 'medium',
    due_date TEXT,
    status TEXT DEFAULT 'pending',
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    remind_at TEXT NOT NULL,
    content TEXT NOT NULL,
    recurring TEXT,
    status TEXT DEFAULT 'active',
    fired_at TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY,
    chat_id TEXT,
    role TEXT,
    agent TEXT,
    content TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()


# ── Memo CRUD ──────────────────────────────────────────

def add_memo(content: str, category: str = 'general', tags: str = '', pinned: bool = False) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO memos (content, category, tags, pinned) VALUES (?, ?, ?, ?)",
        (content, category, tags, int(pinned))
    )
    conn.commit()
    mid = cur.lastrowid
    conn.close()
    return mid


def list_memos(category: str = None, limit: int = 10, pinned_only: bool = False) -> list[dict]:
    conn = get_conn()
    sql = "SELECT * FROM memos"
    params = []
    wheres = []
    if category:
        wheres.append("category = ?")
        params.append(category)
    if pinned_only:
        wheres.append("pinned = 1")
    if wheres:
        sql += " WHERE " + " AND ".join(wheres)
    sql += " ORDER BY pinned DESC, created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_memos(query: str, limit: int = 10) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM memos WHERE content LIKE ? OR tags LIKE ? ORDER BY created_at DESC LIMIT ?",
        (f"%{query}%", f"%{query}%", limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_memo(memo_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM memos WHERE id = ?", (memo_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def pin_memo(memo_id: int, pinned: bool = True) -> bool:
    conn = get_conn()
    cur = conn.execute("UPDATE memos SET pinned = ? WHERE id = ?", (int(pinned), memo_id))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


# ── Todo CRUD ──────────────────────────────────────────

def add_todo(content: str, priority: str = 'medium', due_date: str = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO todos (content, priority, due_date) VALUES (?, ?, ?)",
        (content, priority, due_date)
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def list_todos(status: str = 'pending', limit: int = 20) -> list[dict]:
    conn = get_conn()
    if status == 'all':
        rows = conn.execute(
            "SELECT * FROM todos ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM todos WHERE status = ? ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, due_date ASC NULLS LAST, created_at DESC LIMIT ?",
            (status, limit)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def complete_todo(todo_id: int) -> bool:
    conn = get_conn()
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    cur = conn.execute(
        "UPDATE todos SET status = 'done', completed_at = ? WHERE id = ? AND status = 'pending'",
        (now, todo_id)
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def cancel_todo(todo_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute(
        "UPDATE todos SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
        (todo_id,)
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def delete_todo(todo_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


# ── Reminder CRUD ──────────────────────────────────────

def add_reminder(content: str, remind_at: str, recurring: str = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO reminders (content, remind_at, recurring) VALUES (?, ?, ?)",
        (content, remind_at, recurring)
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def list_reminders(status: str = 'active', limit: int = 20) -> list[dict]:
    conn = get_conn()
    if status == 'all':
        rows = conn.execute(
            "SELECT * FROM reminders ORDER BY remind_at ASC LIMIT ?",
            (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE status = ? ORDER BY remind_at ASC LIMIT ?",
            (status, limit)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_due_reminders() -> list[dict]:
    conn = get_conn()
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    rows = conn.execute(
        "SELECT * FROM reminders WHERE status = 'active' AND remind_at <= ?",
        (now,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_fired(reminder_id: int):
    conn = get_conn()
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    conn.execute(
        "UPDATE reminders SET status = 'fired', fired_at = ? WHERE id = ?",
        (now, reminder_id)
    )
    conn.commit()
    conn.close()


def reschedule_reminder(reminder_id: int, next_at: str):
    conn = get_conn()
    conn.execute(
        "UPDATE reminders SET remind_at = ? WHERE id = ?",
        (next_at, reminder_id)
    )
    conn.commit()
    conn.close()


def cancel_reminder(reminder_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute(
        "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'active'",
        (reminder_id,)
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


# ── Conversation Log ───────────────────────────────────

def save_conversation(chat_id: str, role: str, content: str, agent: str = ''):
    conn = get_conn()
    conn.execute(
        "INSERT INTO conversations (chat_id, role, agent, content) VALUES (?, ?, ?, ?)",
        (chat_id, role, agent, content[:1000])
    )
    conn.commit()
    conn.close()


def get_recent_conversations(chat_id: str, limit: int = 6) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM conversations WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (chat_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def cleanup_old_conversations(days: int = 90):
    """N일 이상 된 대화 로그 삭제."""
    conn = get_conn()
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    cur = conn.execute("DELETE FROM conversations WHERE created_at < ?", (cutoff,))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted


def get_stats() -> dict:
    conn = get_conn()
    stats = {}
    stats['memos'] = conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0]
    stats['todos_pending'] = conn.execute("SELECT COUNT(*) FROM todos WHERE status='pending'").fetchone()[0]
    stats['todos_done'] = conn.execute("SELECT COUNT(*) FROM todos WHERE status='done'").fetchone()[0]
    stats['reminders_active'] = conn.execute("SELECT COUNT(*) FROM reminders WHERE status='active'").fetchone()[0]
    stats['conversations'] = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    conn.close()
    return stats


# ── CLI ────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='비서 DB 관리')
    parser.add_argument('--init', action='store_true', help='DB 초기화')
    parser.add_argument('--stats', action='store_true', help='통계 출력')
    args = parser.parse_args()

    init_db()

    if args.stats:
        s = get_stats()
        print(f"메모: {s['memos']}개")
        print(f"할일: 대기 {s['todos_pending']}개 / 완료 {s['todos_done']}개")
        print(f"리마인더: 활성 {s['reminders_active']}개")
        print(f"대화: {s['conversations']}건")
    elif args.init:
        print(f"DB 초기화 완료: {DB_PATH}")
    else:
        s = get_stats()
        print(f"assistant.db — 메모 {s['memos']} / 할일 {s['todos_pending']} / 리마인더 {s['reminders_active']} / 대화 {s['conversations']}")
