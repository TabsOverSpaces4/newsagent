"""Stage 3: score stories against the interest profile, keep the top N.

Score = cosine similarity to the interest profile x source weight. Similarity
comes from embedding the title plus a cleaned snippet of the feed summary,
which carries more signal than the title alone.
"""

from __future__ import annotations

import re

import numpy as np

from .models import Story

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def ranking_text(story: Story, snippet_words: int = 60) -> str:
    snippet = _WS_RE.sub(" ", _TAG_RE.sub(" ", story.entry.feed_summary)).strip()
    snippet = " ".join(snippet.split()[:snippet_words])
    return f"{story.entry.title}. {snippet}".strip()


def rank(
    stories: list[Story],
    story_vectors: np.ndarray,
    interest_vector: np.ndarray,
    top_n: int = 50,
    boosts: dict[int, float] | None = None,
) -> tuple[list[Story], list[Story]]:
    """Returns (kept, dropped), kept sorted by score descending.

    If boosts is provided, each story's score is multiplied by the
    corresponding boost value (default 1.0) after cosine similarity.
    """
    for i, (story, vec) in enumerate(zip(stories, story_vectors, strict=True)):
        score = float(np.dot(vec, interest_vector)) * story.entry.weight
        if boosts:
            score *= boosts.get(i, 1.0)
        story.score = score
    ordered = sorted(stories, key=lambda s: s.score, reverse=True)
    return ordered[:top_n], ordered[top_n:]
