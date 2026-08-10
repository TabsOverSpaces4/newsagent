"""Stage 2: canonicalize URLs, drop already-seen items, cluster near-duplicate
stories by title embedding.

Split into pure pieces so each is testable without the network:
- canonicalize(): pure string transform
- resolve_redirects(): the only network step (best-effort HEAD)
- filter_new(): seen-table + intra-run hash dedupe
- cluster(): greedy clustering over precomputed title vectors
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sqlite3
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import numpy as np

from . import state
from .models import Entry, Story

log = logging.getLogger(__name__)

TRACKING_PARAMS = ("fbclid", "ref", "gclid")
REDIRECT_TIMEOUT = 10.0
REDIRECT_CONCURRENCY = 10


def canonicalize(url: str) -> str:
    """Lowercase the host, strip tracking params, drop fragment/trailing slash."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") if parts.path != "/" else ""
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(query), ""))


def url_hash(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode()).hexdigest()


async def resolve_redirects(entries: list[Entry], user_agent: str) -> None:
    """Best-effort: follow redirects so mirrors of one URL hash identically.

    Fills entry.canonical_url and entry.url_hash in place. Any failure falls
    back to the raw URL; this step must never kill the run.
    """
    sem = asyncio.Semaphore(REDIRECT_CONCURRENCY)

    async def resolve(client: httpx.AsyncClient, entry: Entry) -> None:
        final = entry.raw_url
        async with sem:
            try:
                resp = await client.head(entry.raw_url, timeout=REDIRECT_TIMEOUT)
                final = str(resp.url)
            except Exception:
                pass  # keep the raw URL
        entry.canonical_url = canonicalize(final)
        entry.url_hash = url_hash(entry.canonical_url)

    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent}, follow_redirects=True
    ) as client:
        await asyncio.gather(*(resolve(client, e) for e in entries))


def finalize_urls(entries: list[Entry]) -> None:
    """Offline fallback for tests/fixtures: canonicalize without the network."""
    for entry in entries:
        entry.canonical_url = canonicalize(entry.raw_url)
        entry.url_hash = url_hash(entry.canonical_url)


def filter_new(entries: list[Entry], conn: sqlite3.Connection) -> list[Entry]:
    """Drop entries already in the seen table, and same-run hash duplicates."""
    fresh: list[Entry] = []
    run_hashes: set[str] = set()
    for entry in entries:
        if entry.url_hash in run_hashes or state.is_seen(conn, entry.url_hash):
            continue
        run_hashes.add(entry.url_hash)
        fresh.append(entry)
    return fresh


def cluster(entries: list[Entry], vectors: np.ndarray, threshold: float = 0.85) -> list[Story]:
    """Greedy story-level dedupe over normalized title vectors.

    Entries are visited highest-weight first, so each cluster's representative
    is automatically the highest-weight source; later members become related
    links. Cosine similarity is a dot product because vectors are normalized.
    """
    order = sorted(range(len(entries)), key=lambda i: (-entries[i].weight, entries[i].title))
    stories: list[Story] = []
    rep_vectors: list[np.ndarray] = []
    for i in order:
        entry, vec = entries[i], vectors[i]
        best_j, best_sim = -1, threshold
        for j, rep_vec in enumerate(rep_vectors):
            sim = float(np.dot(vec, rep_vec))
            if sim >= best_sim:
                best_j, best_sim = j, sim
        if best_j >= 0:
            stories[best_j].related.append(entry)
        else:
            stories.append(Story(entry=entry))
            rep_vectors.append(vec)
    if len(stories) < len(entries):
        log.info(
            "clustered entries=%d stories=%d merged=%d",
            len(entries),
            len(stories),
            len(entries) - len(stories),
        )
    return stories
