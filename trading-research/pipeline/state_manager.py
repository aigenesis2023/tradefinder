"""
State manager — minimal SQLite logging for the insider-cluster pipeline.

Stores each detected cluster signal so the operator can track what was surfaced
and when. No dedup logic, no regime logging, no outcome tracking — just a
simple append-only log of daily scan results.
"""

import sqlite3
from datetime import datetime, date
from pathlib import Path


DB_PATH = Path(__file__).parent.parent / "data" / "trading_research.db"


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the signals table if it doesn't exist."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                run_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                signal_date TEXT,
                cluster_start TEXT,
                cluster_end TEXT,
                unique_insiders INTEGER,
                opportunistic_count INTEGER,
                total_usd REAL,
                insider_names TEXT,
                insider_roles TEXT,
                company_name TEXT,
                market_cap_m REAL,
                created_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (run_id, ticker)
            );
        """)


def log_signal(run_id: str, data: dict):
    """Insert or update a signal record for this run."""
    cols = ", ".join(data.keys())
    placeholders = ", ".join("?" * len(data))
    update_cols = ", ".join(f"{k}=excluded.{k}" for k in data if k not in ("run_id", "ticker"))

    with get_conn() as conn:
        conn.execute(
            f"""INSERT INTO signals (run_id, {cols})
                VALUES (?, {placeholders})
                ON CONFLICT(run_id, ticker) DO UPDATE SET {update_cols}""",
            [run_id] + list(data.values())
        )
