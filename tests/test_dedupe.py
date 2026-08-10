import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from digest import state
from digest.dedupe import cluster, filter_new, finalize_urls
from digest.ingest import parse_entries
from digest.models import Entry, Feed

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def make_entry(title: str, url: str, source: str = "A", weight: float = 1.0) -> Entry:
    return Entry(title=title, raw_url=url, source=source, weight=weight)


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def test_parse_entries_window_and_undated():
    feed = Feed(url="https://example.com/feed", name="Example Chip News")
    content = (FIXTURES / "feed_basic.xml").read_bytes()
    entries = parse_entries(feed, content, now=NOW, window_hours=48)
    titles = [e.title for e in entries]
    assert "TSMC announces 1.4nm process roadmap" in titles
    assert "Undated analog PLL deep dive" in titles  # no timestamp -> included
    assert "Old story outside the window" not in titles
    assert "Entry with no link is skipped" not in titles


def test_filter_new_drops_seen_and_intra_run_dupes(tmp_path):
    conn = state.connect(tmp_path / "digest.db")
    a = make_entry("Story A", "https://example.com/a?utm_source=x")
    a_dup = make_entry("Story A again", "https://example.com/a/")  # same canonical URL
    b = make_entry("Story B", "https://example.com/b")
    c = make_entry("Story C", "https://example.com/c")
    finalize_urls([a, a_dup, b, c])

    state.mark_seen(conn, [c])  # C was in yesterday's run
    fresh = filter_new([a, a_dup, b, c], conn)
    assert [e.title for e in fresh] == ["Story A", "Story B"]


# Known set of near-duplicate headlines: the same two announcements as covered
# by different outlets, plus two unrelated stories. Vectors are hand-built so
# the test is deterministic and needs no model download.
HEADLINES = [
    # cluster 1: Nvidia B300 launch (3 outlets)
    ("Nvidia unveils B300 AI accelerator at GTC", "EE Times", 1.3, [1.0, 0.05, 0.0]),
    ("Nvidia launches new B300 GPU for AI datacenters", "Tom's Hardware", 0.8, [0.98, 0.1, 0.0]),
    ("GTC 2026: Nvidia's B300 accelerator announced", "The Register", 0.7, [0.97, 0.08, 0.05]),
    # cluster 2: TI earnings (2 outlets)
    ("Texas Instruments beats Q2 estimates on analog demand", "EE Times", 1.3, [0.0, 1.0, 0.1]),
    ("TI Q2 earnings top expectations, analog leads", "Reuters", 1.0, [0.05, 0.99, 0.1]),
    # singletons
    ("Cadence adds RL-based placement to Innovus", "SemiEngineering", 1.5, [0.1, 0.1, 1.0]),
    ("Imec shows 2D-material transistor progress", "IEEE Spectrum", 1.3, [0.55, 0.5, 0.66]),
]


def test_cluster_near_duplicate_headlines():
    entries = [
        make_entry(t, f"https://example.com/{i}", src, w)
        for i, (t, src, w, _) in enumerate(HEADLINES)
    ]
    vectors = np.stack([unit(v) for _, _, _, v in HEADLINES])
    stories = cluster(entries, vectors, threshold=0.85)

    assert len(stories) == 4
    by_rep = {s.entry.title: s for s in stories}

    # Highest-weight outlet is the representative; others are related links.
    nvidia = by_rep["Nvidia unveils B300 AI accelerator at GTC"]
    assert nvidia.entry.source == "EE Times"
    assert {e.source for e in nvidia.related} == {"Tom's Hardware", "The Register"}

    ti = by_rep["Texas Instruments beats Q2 estimates on analog demand"]
    assert len(ti.related) == 1 and ti.related[0].source == "Reuters"

    assert by_rep["Cadence adds RL-based placement to Innovus"].related == []
    assert by_rep["Imec shows 2D-material transistor progress"].related == []


def test_cluster_threshold_boundary():
    a = make_entry("A", "https://example.com/a")
    b = make_entry("B", "https://example.com/b")
    vectors = np.stack([unit([1.0, 0.0]), unit([1.0, 1.0])])  # cosine sim ~0.707
    assert len(cluster([a, b], vectors, threshold=0.85)) == 2
    assert len(cluster([a, b], vectors, threshold=0.7)) == 1


@pytest.mark.skipif(
    os.environ.get("DIGEST_MODEL_TESTS") != "1",
    reason="set DIGEST_MODEL_TESTS=1 to run the real-embedding test (downloads model)",
)
def test_cluster_with_real_embeddings():
    from digest.embeddings import embed

    entries = [
        make_entry(t, f"https://example.com/{i}", src, w)
        for i, (t, src, w, _) in enumerate(HEADLINES)
    ]
    vectors = embed([e.title for e in entries])
    stories = cluster(entries, vectors, threshold=0.85)
    # The three Nvidia B300 headlines must merge; unrelated stories must not.
    assert len(stories) < len(entries)
    reps = [s.entry.title for s in stories]
    assert "Cadence adds RL-based placement to Innovus" in reps
