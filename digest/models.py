"""Shared data models for the pipeline and the LLM response shape."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Feed(BaseModel):
    url: str
    name: str
    weight: float = 1.0


class Entry(BaseModel):
    """One item pulled from a feed, before dedupe."""

    title: str
    raw_url: str
    canonical_url: str = ""
    url_hash: str = ""
    source: str
    weight: float = 1.0
    published: datetime | None = None
    feed_summary: str = ""


class Story(BaseModel):
    """A deduplicated story cluster: one representative entry plus related links."""

    entry: Entry
    related: list[Entry] = Field(default_factory=list)
    score: float = 0.0
    text: str = ""


class DigestStory(BaseModel):
    headline: str
    summary: str
    why_it_matters: str
    url: str
    source: str
    related_urls: list[str] = Field(default_factory=list)


class DigestSection(BaseModel):
    title: str
    stories: list[DigestStory]


class DigestResponse(BaseModel):
    # The prompt asks for 3-5 sections; the schema allows 1-5 so that a thin
    # news day (or a --limit run) doesn't fail validation on section count.
    lede: str
    sections: list[DigestSection] = Field(min_length=1, max_length=5)
