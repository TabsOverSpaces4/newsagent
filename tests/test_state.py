import sqlite3
from datetime import UTC, datetime, timedelta

from digest import state
from digest.models import Entry


def make_entry(i: int) -> Entry:
    return Entry(
        title=f"Story {i}",
        raw_url=f"https://example.com/{i}?utm_source=x",
        canonical_url=f"https://example.com/{i}",
        url_hash=f"hash{i}",
        source="Example",
    )


def test_seen_roundtrip(tmp_path):
    conn = state.connect(tmp_path / "digest.db")
    assert not state.is_seen(conn, "hash1")
    state.mark_seen(conn, [make_entry(1), make_entry(2)])
    assert state.is_seen(conn, "hash1")
    assert state.is_seen(conn, "hash2")
    # Re-marking the same entry is a no-op, not an error.
    state.mark_seen(conn, [make_entry(1)])


def test_already_sent_guard(tmp_path):
    conn = state.connect(tmp_path / "digest.db")
    assert not state.already_sent(conn, "2026-08-10")

    # Marker is written before the send call; a retry must see it even if
    # the run never reached mark_sent.
    state.mark_sending(conn, "2026-08-10", story_count=12)
    assert state.already_sent(conn, "2026-08-10")

    state.mark_sent(conn, "2026-08-10")
    assert state.already_sent(conn, "2026-08-10")
    # Other days are unaffected.
    assert not state.already_sent(conn, "2026-08-11")


def test_failed_run_does_not_block_retry(tmp_path):
    conn = state.connect(tmp_path / "digest.db")
    state.mark_failed(conn, "2026-08-10", "llm error")
    assert not state.already_sent(conn, "2026-08-10")
    # A failure recorded after a successful send must not clobber the marker.
    state.mark_sending(conn, "2026-08-10", 5)
    state.mark_failed(conn, "2026-08-10", "late failure")
    assert state.already_sent(conn, "2026-08-10")


def test_prune_seen(tmp_path):
    db = tmp_path / "digest.db"
    conn = state.connect(db)
    state.mark_seen(conn, [make_entry(1), make_entry(2)])
    old = (datetime.now(UTC) - timedelta(days=45)).isoformat()
    conn.execute("UPDATE seen SET first_seen = ? WHERE url_hash = 'hash1'", (old,))
    conn.commit()

    removed = state.prune_seen(conn, days=30)
    assert removed == 1
    assert not state.is_seen(conn, "hash1")
    assert state.is_seen(conn, "hash2")


def test_connect_creates_parent_dir(tmp_path):
    db = tmp_path / "nested" / "dir" / "digest.db"
    conn = state.connect(db)
    assert isinstance(conn, sqlite3.Connection)
    assert db.exists()
