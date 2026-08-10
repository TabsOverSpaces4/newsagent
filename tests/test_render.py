from pathlib import Path

from digest.render import clean_digest, render, scrub, subject_line
from digest.summarize import load_fixture_response

FIXTURES = Path(__file__).parent / "fixtures"


def test_scrub_em_dashes():
    assert scrub("fast — and cheap") == "fast, and cheap"
    assert scrub("fast—and cheap") == "fast, and cheap"
    # en dashes in ranges survive (only em dashes are banned)
    assert scrub("2026–2027 roadmap") == "2026–2027 roadmap"


def test_scrub_emoji():
    assert scrub("Big launch \U0001f680 today ✅") == "Big launch  today"
    assert scrub("plain text stays") == "plain text stays"


def test_clean_digest_scrubs_all_fields():
    digest = load_fixture_response(FIXTURES / "llm_response.json")
    digest.lede = "One thing — two things \U0001f916"
    digest.sections[0].title = "Foundry — Process"
    digest.sections[0].stories[0].headline = "TSMC — onward"
    cleaned = clean_digest(digest)
    assert "—" not in cleaned.lede
    assert "\U0001f916" not in cleaned.lede
    assert cleaned.sections[0].title == "Foundry, Process"
    assert cleaned.sections[0].stories[0].headline == "TSMC, onward"


def test_render_html_and_text():
    digest = load_fixture_response(FIXTURES / "llm_response.json")
    html, text = render(digest, run_date="2026-08-10")

    # Layout basics
    assert "max-width:600px" in html
    assert "2026-08-10" in html
    # Every story links out
    assert 'href="https://example.com/tsmc-14a"' in html
    assert 'href="https://example.com/nvidia-b300"' in html
    assert 'href="https://example.com/cadence-rl-placement"' in html
    # Related links appear
    assert 'href="https://example.com/tsmc-14a-analysis"' in html
    # Unsubscribe line in the footer
    assert "unsubscribe" in html.lower()
    # No emojis or em dashes anywhere in output
    assert "—" not in html and "—" not in text

    # Plaintext mirrors the content
    assert "CHIP DIGEST 2026-08-10" in text
    assert "https://example.com/tsmc-14a" in text
    assert "unsubscribe" in text.lower()


def test_render_escapes_html_in_content():
    digest = load_fixture_response(FIXTURES / "llm_response.json")
    digest.sections[0].stories[0].headline = 'Attack <script>alert("x")</script>'
    html, text = render(digest, run_date="2026-08-10")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    # plaintext is not HTML-escaped
    assert "<script>" in text


def test_subject_line():
    assert subject_line("2026-08-10") == "Chip Digest 2026-08-10"
