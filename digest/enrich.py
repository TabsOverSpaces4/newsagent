"""Stage 4: fetch article pages politely and extract main text with trafilatura.

Max 5 concurrent fetches, 20s timeout, no retries: anything that fails (paywall,
timeout, bot wall) keeps its feed summary and moves on. Never kills the run.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import trafilatura

from .models import Story

log = logging.getLogger(__name__)

FETCH_TIMEOUT = 20.0
CONCURRENCY = 5


def extract_text(html: str, max_words: int = 3000) -> str:
    """Pure extraction + word cap; empty string when trafilatura finds nothing."""
    text = trafilatura.extract(html) or ""
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words])
    return text


async def enrich(stories: list[Story], user_agent: str, max_words: int = 3000) -> int:
    """Fill story.text in place. Returns how many articles yielded text."""
    sem = asyncio.Semaphore(CONCURRENCY)

    async def fetch_one(client: httpx.AsyncClient, story: Story) -> None:
        url = story.entry.canonical_url or story.entry.raw_url
        async with sem:
            try:
                resp = await client.get(url, timeout=FETCH_TIMEOUT)
                resp.raise_for_status()
            except Exception as exc:
                log.info("enrich skip url=%s error=%s: %s", url, type(exc).__name__, exc)
                return
        story.text = extract_text(resp.text, max_words)

    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent}, follow_redirects=True
    ) as client:
        await asyncio.gather(*(fetch_one(client, s) for s in stories))

    enriched = sum(1 for s in stories if s.text)
    log.info("enrich done ok=%d skipped=%d", enriched, len(stories) - enriched)
    return enriched
