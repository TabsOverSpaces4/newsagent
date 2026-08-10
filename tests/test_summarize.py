from pathlib import Path
from types import SimpleNamespace

import pytest

from digest import summarize as summarize_mod
from digest.models import DigestResponse, Entry, Story
from digest.summarize import SummarizeError, load_fixture_response, summarize

FIXTURES = Path(__file__).parent / "fixtures"


def make_stories() -> list[Story]:
    return [
        Story(
            entry=Entry(
                title="TSMC announces 1.4nm process roadmap",
                raw_url="https://example.com/tsmc-14a",
                canonical_url="https://example.com/tsmc-14a",
                source="Example Chip News",
            ),
            text="TSMC laid out its A14 roadmap.",
        )
    ]


def good_response() -> SimpleNamespace:
    return SimpleNamespace(
        parsed_output=load_fixture_response(FIXTURES / "llm_response.json"),
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=100, output_tokens=200),
    )


def bad_response() -> SimpleNamespace:
    return SimpleNamespace(
        parsed_output=None,
        stop_reason="max_tokens",
        usage=SimpleNamespace(input_tokens=100, output_tokens=200),
    )


class FakeClient:
    """Stands in for anthropic.Anthropic; returns queued responses in order."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def install(monkeypatch, fake: FakeClient) -> None:
    monkeypatch.setattr(summarize_mod.anthropic, "Anthropic", lambda api_key: fake)


def test_fixture_response_is_valid():
    digest = load_fixture_response(FIXTURES / "llm_response.json")
    assert isinstance(digest, DigestResponse)
    assert 1 <= len(digest.sections) <= 5


def test_success_first_try(monkeypatch):
    fake = FakeClient([good_response()])
    install(monkeypatch, fake)
    digest = summarize(make_stories(), "interests", api_key="k")
    assert digest.lede.startswith("TSMC")
    assert len(fake.calls) == 1


def test_malformed_then_retry_succeeds(monkeypatch):
    fake = FakeClient([bad_response(), good_response()])
    install(monkeypatch, fake)
    digest = summarize(make_stories(), "interests", api_key="k")
    assert isinstance(digest, DigestResponse)
    assert len(fake.calls) == 2
    # The retry must carry the parse error back to the model.
    retry_messages = fake.calls[1]["messages"]
    assert len(retry_messages) == 2
    assert "could not be parsed" in retry_messages[1]["content"]


def test_fails_twice_raises(monkeypatch):
    fake = FakeClient([bad_response(), ValueError("still broken")])
    install(monkeypatch, fake)
    with pytest.raises(SummarizeError, match="failed twice"):
        summarize(make_stories(), "interests", api_key="k")
    assert len(fake.calls) == 2


def test_refusal_raises_immediately(monkeypatch):
    refusal = SimpleNamespace(
        parsed_output=None,
        stop_reason="refusal",
        usage=SimpleNamespace(input_tokens=1, output_tokens=0),
    )
    fake = FakeClient([refusal])
    install(monkeypatch, fake)
    with pytest.raises(SummarizeError, match="refused"):
        summarize(make_stories(), "interests", api_key="k")
    assert len(fake.calls) == 1


def test_prompt_contains_urls_and_interests():
    prompt = summarize_mod.build_user_prompt(make_stories(), "analog design")
    assert "analog design" in prompt
    assert "https://example.com/tsmc-14a" in prompt
    assert "TSMC laid out its A14 roadmap." in prompt
