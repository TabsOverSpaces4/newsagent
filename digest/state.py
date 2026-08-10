"""SQLite state: seen-URL table and per-day run markers.

The send marker is written BEFORE the Resend call so a retried run on the same
day exits cleanly instead of double-sending. The tradeoff (a crash between
marker and send means no email that day) is intentional: a missing digest is
better than a duplicate one, and --force exists for recovery.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import Entry

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    url_hash TEXT PRIMARY KEY,
    canonical_url TEXT,
    title TEXT,
    source TEXT,
    first_seen TIMESTAMP
);
CREATE TABLE IF NOT EXISTS runs (
    run_date TEXT PRIMARY KEY,
    sent_at TIMESTAMP,
    story_count INTEGER,
    status TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def is_seen(conn: sqlite3.Connection, url_hash: str) -> bool:
    row = conn.execute("SELECT 1 FROM seen WHERE url_hash = ?", (url_hash,)).fetchone()
    return row is not None


def mark_seen(conn: sqlite3.Connection, entries: list[Entry]) -> None:
    now = datetime.now(UTC).isoformat()
    conn.executemany(
        "INSERT OR IGNORE INTO seen (url_hash, canonical_url, title, source, first_seen)"
        " VALUES (?, ?, ?, ?, ?)",
        [(e.url_hash, e.canonical_url, e.title, e.source, now) for e in entries],
    )
    conn.commit()


def already_sent(conn: sqlite3.Connection, run_date: str) -> bool:
    """True if a send was started (or completed) for run_date."""
    row = conn.execute(
        "SELECT 1 FROM runs WHERE run_date = ? AND status IN ('sending', 'sent')",
        (run_date,),
    ).fetchone()
    return row is not None


def mark_sending(conn: sqlite3.Connection, run_date: str, story_count: int) -> None:
    """Write the marker row. Called immediately before the send API call."""
    conn.execute(
        "INSERT OR REPLACE INTO runs (run_date, sent_at, story_count, status)"
        " VALUES (?, NULL, ?, 'sending')",
        (run_date, story_count),
    )
    conn.commit()


def mark_sent(conn: sqlite3.Connection, run_date: str) -> None:
    conn.execute(
        "UPDATE runs SET sent_at = ?, status = 'sent' WHERE run_date = ?",
        (datetime.now(UTC).isoformat(), run_date),
    )
    conn.commit()


def mark_failed(conn: sqlite3.Connection, run_date: str, reason: str) -> None:
    """Record a failed run without blocking a same-day retry."""
    if already_sent(conn, run_date):
        return
    conn.execute(
        "INSERT OR REPLACE INTO runs (run_date, sent_at, story_count, status)"
        " VALUES (?, NULL, 0, ?)",
        (run_date, f"failed: {reason}"),
    )
    conn.commit()


def prune_seen(conn: sqlite3.Connection, days: int = 30) -> int:
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    cur = conn.execute("DELETE FROM seen WHERE first_seen < ?", (cutoff,))
    conn.commit()
    return cur.rowcount
