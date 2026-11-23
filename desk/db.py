"""SQLite store for odds snapshots, projections and board entries (data/desk.db)."""
from __future__ import annotations

import os
import sqlite3

DB_PATH = os.environ.get("DESK_DB", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "desk.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS odds_snapshots (
    taken_at TEXT, kind TEXT, sport TEXT, event_id TEXT, commence TEXT,
    home TEXT, away TEXT, book TEXT, market TEXT, player TEXT,
    side TEXT, point REAL, price REAL
);
CREATE INDEX IF NOT EXISTS ix_odds_event ON odds_snapshots(event_id, market, player, side, point);
CREATE TABLE IF NOT EXISTS projections (
    created_at TEXT, game_date TEXT, sport TEXT, event TEXT, player TEXT, team TEXT,
    market TEXT, mean REAL, sd REAL, minutes REAL, model TEXT
);
CREATE TABLE IF NOT EXISTS board (
    created_at TEXT, game_date TEXT, session TEXT, sport TEXT, event TEXT, player TEXT,
    market TEXT, side TEXT, line REAL, model_prob REAL, fair_market_prob REAL,
    dk_price REAL, fd_price REAL, pin_price REAL, best_book TEXT, best_price REAL,
    edge REAL, kelly_stake REAL, model TEXT
);
"""


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def insert_many(con: sqlite3.Connection, table: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = list(rows[0].keys())
    con.executemany(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        [tuple(r.get(c) for c in cols) for r in rows],
    )
    con.commit()
    return len(rows)
