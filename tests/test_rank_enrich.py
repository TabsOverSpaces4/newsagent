from pathlib import Path

import numpy as np

from digest.enrich import extract_text
from digest.models import Entry, Story
from digest.rank import rank, ranking_text

FIXTURES = Path(__file__).parent / "fixtures"


def make_story(title: str, weight: float = 1.0, summary: str = "") -> Story:
    return Story(
        entry=Entry(
            title=title,
            raw_url=f"https://example.com/{title[:8]}",
            source="Test",
            weight=weight,
            feed_summary=summary,
        )
    )


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def test_rank_orders_by_similarity_and_weight():
    interest = unit([1.0, 0.0])
    stories = [
        make_story("on-topic low weight", weight=0.5),
        make_story("on-topic high weight", weight=1.5),
        make_story("off-topic", weight=1.5),
    ]
    vectors = np.stack([unit([1.0, 0.0]), unit([1.0, 0.0]), unit([0.0, 1.0])])
    kept, dropped = rank(stories, vectors, interest, top_n=2)

    assert [s.entry.title for s in kept] == ["on-topic high weight", "on-topic low weight"]
    assert [s.entry.title for s in dropped] == ["off-topic"]
    assert kept[0].score > kept[1].score > dropped[0].score


def test_ranking_text_strips_html_and_caps_words():
    story = make_story("Title here", summary="<p>Some <b>bold</b> summary text.</p>")
    assert ranking_text(story) == "Title here. Some bold summary text."
    long_summary = " ".join(f"w{i}" for i in range(200))
    capped = ranking_text(make_story("T", summary=long_summary), snippet_words=10)
    assert capped == "T. " + " ".join(f"w{i}" for i in range(10))


def test_extract_text_pulls_article_body():
    html = (FIXTURES / "article.html").read_text()
    text = extract_text(html)
    assert "A14 process roadmap" in text
    assert "nanosheet transistors" in text
    # boilerplate should be gone
    assert "Subscribe to our newsletter" not in text


def test_extract_text_word_cap():
    html = (
        "<html><body><article><p>"
        + " ".join(f"word{i}" for i in range(100))
        + "</p></article></body></html>"
    )
    text = extract_text(html, max_words=20)
    assert text == "" or len(text.split()) <= 20


def test_extract_text_handles_garbage():
    assert extract_text("not html at all") == ""
