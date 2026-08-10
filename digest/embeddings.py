"""Lazy sentence-transformers wrapper.

The model (~90MB) loads on first use only, so tests and --help never touch it.
"""

from __future__ import annotations

from functools import cache

import numpy as np

MODEL_NAME = "all-MiniLM-L6-v2"


@cache
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def embed(texts: list[str]) -> np.ndarray:
    """Return one L2-normalized vector per text; cosine similarity = dot product."""
    return _model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
