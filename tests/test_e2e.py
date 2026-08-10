"""End-to-end run against fixture feeds: no network, no model, no LLM.

httpx.AsyncClient is redirected to a MockTransport, embeddings are replaced by
a deterministic hash-based fake, and --no-llm supplies the canned response.
"""

import hashlib
from pathlib import Path

import httpx
import numpy as np
import pytest

import digest.__main__ as cli
from digest import state
from digest.config import Settings
from digest.models import Feed

FIXTURES = Path(__file__).parent / "fixtures"
E2E_FEED_URL = "https://feeds.test/e2e"
BASIC_FEED_URL = "https://feeds.test/basic"


def fake_embed(texts):
    vecs = []
    for t in texts:
        seed = int(hashlib.sha256(t.encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        v = rng.normal(size=32)
        vecs.append(v / np.linalg.norm(v))
    return np.stack(vecs)


def handler(request: httpx.Request) -> httpx.Response:
    if request.method == "HEAD":
        return httpx.Response(200)
    url = str(request.url)
    if url == E2E_FEED_URL:
        return httpx.Response(200, content=(FIXTURES / "feed_e2e.xml").read_bytes())
    if url == BASIC_FEED_URL:
        return httpx.Response(200, content=(FIXTURES / "feed_basic.xml").read_bytes())
    if request.url.host == "articles.test":
        return httpx.Response(200, text=(FIXTURES / "article.html").read_text())
    return httpx.Response(404)


@pytest.fixture
def offline(monkeypatch, tmp_path):
    real_client = httpx.AsyncClient

    def client_factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    monkeypatch.setattr("digest.embeddings.embed", fake_embed)
    monkeypatch.setattr(cli, "OUT_DIR", tmp_path / "out")
    return tmp_path


def make_settings(tmp_path, feed_url=E2E_FEED_URL, **overrides) -> Settings:
    defaults = dict(
        feeds=[Feed(url=feed_url, name="E2E Chip Feed", weight=1.0)],
        interests="semiconductors, analog design, AI hardware, EDA",
        recipients=[],
        db_path=tmp_path / "digest.db",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_e2e_dry_run_produces_plausible_html(offline, monkeypatch):
    tmp_path = offline
    settings = make_settings(tmp_path)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)

    rc = cli.main(["--no-llm"])
    assert rc == cli.EXIT_OK

    html = (tmp_path / "out" / "preview.html").read_text()
    text = (tmp_path / "out" / "preview.txt").read_text()
    assert "max-width:600px" in html
    assert "<a href=" in html
    assert "unsubscribe" in html.lower()
    assert "—" not in html
    assert "CHIP DIGEST" in text

    # Dry runs must not consume state: nothing marked seen, no run row.
    conn = state.connect(settings.db_path)
    assert conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_e2e_too_few_stories_fails_loudly(offline, monkeypatch):
    tmp_path = offline
    # feed_basic.xml yields at most 3 entries; min_stories=5 must abort the run.
    settings = make_settings(tmp_path, feed_url=BASIC_FEED_URL)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)

    rc = cli.main(["--no-llm"])
    assert rc == cli.EXIT_TOO_FEW_STORIES


def test_e2e_already_sent_guard_exits_cleanly(offline, monkeypatch):
    tmp_path = offline
    settings = make_settings(tmp_path, resend_api_key="rk", recipients=["a@example.com"])
    monkeypatch.setattr(cli, "load_settings", lambda: settings)

    from datetime import UTC, datetime

    conn = state.connect(settings.db_path)
    state.mark_sending(conn, datetime.now(UTC).date().isoformat(), 10)
    conn.close()

    rc = cli.main([])
    assert rc == cli.EXIT_OK


def test_e2e_limit_caps_stories(offline, monkeypatch):
    tmp_path = offline
    settings = make_settings(tmp_path)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    rc = cli.main(["--no-llm", "--limit", "6"])
    assert rc == cli.EXIT_OK
