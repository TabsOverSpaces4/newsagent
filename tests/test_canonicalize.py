import pytest

from digest.dedupe import canonicalize, url_hash

CASES = [
    # host lowercased
    ("https://Example.COM/Article", "https://example.com/Article"),
    # utm_* stripped
    (
        "https://example.com/a?utm_source=rss&utm_medium=feed&utm_campaign=x",
        "https://example.com/a",
    ),
    # fbclid / ref / gclid stripped, real params kept
    ("https://example.com/a?fbclid=abc&id=42", "https://example.com/a?id=42"),
    ("https://example.com/a?ref=hn", "https://example.com/a"),
    ("https://example.com/a?gclid=xyz&page=2", "https://example.com/a?page=2"),
    # trailing slash stripped
    ("https://example.com/article/", "https://example.com/article"),
    # bare root: no spurious trailing artifacts
    ("https://example.com/", "https://example.com"),
    # fragment dropped
    ("https://example.com/a#section-2", "https://example.com/a"),
    # path case is preserved (only host is case-insensitive)
    ("HTTPS://example.com/CamelCase", "https://example.com/CamelCase"),
    # param order preserved, blank values kept
    ("https://example.com/a?b=&a=1", "https://example.com/a?b=&a=1"),
]


@pytest.mark.parametrize("raw,expected", CASES)
def test_canonicalize(raw, expected):
    assert canonicalize(raw) == expected


def test_hash_is_stable_across_variants():
    variants = [
        "https://Example.com/story/?utm_source=x",
        "https://example.com/story?fbclid=123",
        "https://example.com/story/",
    ]
    hashes = {url_hash(canonicalize(v)) for v in variants}
    assert len(hashes) == 1


def test_hash_differs_for_different_urls():
    a = url_hash(canonicalize("https://example.com/story-a"))
    b = url_hash(canonicalize("https://example.com/story-b"))
    assert a != b
