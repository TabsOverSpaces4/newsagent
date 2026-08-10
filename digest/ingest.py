"""Stage 1: fetch all feeds concurrently, parse entries from the last N hours.

A single failing feed never fails the run; failures are counted and the caller
decides (via TooManyFeedFailures) whether the run as a whole is dead.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import feedparser
import httpx

from .models import Entry, Feed

log = logging.getLogger(__name__)

USER_AGENT = "newsagent-digest/1.0 (daily semiconductor news digest; contact via repo issues)"
FEED_TIMEOUT = 15.0


class TooManyFeedFailures(Exception):
    def __init__(self, failed: int, total: int):
        super().__init__(f"{failed}/{total} feeds failed")
        self.failed = failed
        self.total = total


async def _fetch_one(client: httpx.AsyncClient, feed: Feed) -> bytes | None:
    try:
        resp = await client.get(feed.url, timeout=FEED_TIMEOUT)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:
        log.warning("feed failed name=%r url=%s error=%s", feed.name, feed.url, exc)
        return None


def parse_entries(feed: Feed, content: bytes, now: datetime, window_hours: int) -> list[Entry]:
    """Parse one feed's XML into Entries published within the window.

    Entries with no parseable timestamp are included; dedupe handles repeats.
    """
    cutoff = now - timedelta(hours=window_hours)
    parsed = feedparser.parse(content)
    entries: list[Entry] = []
    for item in parsed.entries:
        title = (item.get("title") or "").strip()
        link = (item.get("link") or "").strip()
        if not title or not link:
            continue
        published = None
        struct = item.get("published_parsed") or item.get("updated_parsed")
        if struct:
            published = datetime(*struct[:6], tzinfo=UTC)
            if published < cutoff:
                continue
        entries.append(
            Entry(
                title=title,
                raw_url=link,
                source=feed.name,
                weight=feed.weight,
                published=published,
                feed_summary=(item.get("summary") or "")[:2000],
            )
        )
    return entries


async def ingest(
    feeds: list[Feed],
    window_hours: int = 48,
    max_failure_ratio: float = 0.4,
    now: datetime | None = None,
) -> tuple[list[Entry], int]:
    """Fetch every feed concurrently. Returns (entries, failed_feed_count).

    Raises TooManyFeedFailures if more than max_failure_ratio of feeds failed.
    """
    now = now or datetime.now(UTC)
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        contents = await asyncio.gather(*(_fetch_one(client, f) for f in feeds))

    entries: list[Entry] = []
    failed = 0
    for feed, content in zip(feeds, contents, strict=True):
        if content is None:
            failed += 1
            continue
        feed_entries = parse_entries(feed, content, now, window_hours)
        log.info("feed ok name=%r entries=%d", feed.name, len(feed_entries))
        entries.extend(feed_entries)

    if feeds and failed / len(feeds) > max_failure_ratio:
        raise TooManyFeedFailures(failed, len(feeds))
    return entries, failed
