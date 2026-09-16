"""Fetch reader feedback from the Cloudflare Worker and compute ranking boosts.

Failures are always swallowed so the pipeline never crashes due to feedback.
"""

from __future__ import annotations

import logging
from urllib.error import URLError
from urllib.request import Request, urlopen

import json

from .models import Story

log = logging.getLogger(__name__)

EXPORT_TIMEOUT = 10


def fetch_feedback(worker_url: str, export_secret: str) -> dict:
    """Call the /export endpoint and return parsed JSON.

    Returns an empty dict on any failure so the pipeline is never blocked.
    A 403 is logged as ERROR because it always means a secret mismatch.
    """
    url = f"{worker_url.rstrip('/')}/export?secret={export_secret}"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=EXPORT_TIMEOUT) as resp:
            if resp.status == 403:
                log.error(
                    "feedback export returned 403: FEEDBACK_EXPORT_SECRET does not "
                    "match the Worker's EXPORT_SECRET. The feedback loop is broken "
                    "until you fix this."
                )
                return {}
            if resp.status != 200:
                log.warning("feedback export returned status=%d", resp.status)
                return {}
            return json.loads(resp.read())
    except (URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        if "403" in str(exc):
            log.error(
                "feedback export returned 403: FEEDBACK_EXPORT_SECRET does not "
                "match the Worker's EXPORT_SECRET. The feedback loop is broken "
                "until you fix this."
            )
        else:
            log.warning("feedback fetch failed: %s", exc)
        return {}


def compute_boosts(feedback: dict, stories: list[Story]) -> dict[int, float]:
    """Compute per-story ranking multipliers from source affinity data.

    Source affinity: if a source has avg_score >= 7 with n >= 3 ratings,
    boost by 1.0 + (avg_score - 5) * 0.05. If avg_score < 4 with n >= 3,
    penalize with 0.8x.
    """
    affinity = feedback.get("source_affinity", [])
    source_mult: dict[str, float] = {}
    for row in affinity:
        avg = float(row.get("avg_score", 5))
        count = int(row.get("count", 0))
        source = row.get("source", "")
        if count < 3 or not source:
            continue
        if avg >= 7:
            source_mult[source] = 1.0 + (avg - 5) * 0.05
        elif avg < 4:
            source_mult[source] = 0.8

    boosts: dict[int, float] = {}
    for i, story in enumerate(stories):
        mult = source_mult.get(story.entry.source, 1.0)
        if mult != 1.0:
            boosts[i] = mult
    return boosts
