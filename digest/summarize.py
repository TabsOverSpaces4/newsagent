"""Stage 5: one Claude call producing the digest, validated against
DigestResponse. Structured outputs constrain the response to the schema; the
retry-once-with-error path covers truncation, refusals, and validation edges.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import anthropic

from .models import DigestResponse, Story

log = logging.getLogger(__name__)

MODEL = "claude-opus-4-8"
MAX_TOKENS = 16000

SYSTEM_PROMPT = """\
You write a daily email digest about the semiconductor industry for a reader whose
interests are described in the user message. Today's candidate stories are provided
as JSON, ranked most relevant first.

Output rules:
- Group the stories into 3 to 5 named sections chosen from the day's actual content
  (use fewer sections only if there are fewer than 6 stories). Order sections by
  importance to the reader. You may drop stories that are off-topic or redundant.
- Each story: headline (your own words), summary (2 to 3 sentences), why_it_matters
  (one sentence), plus the story's url, source, and related_urls copied verbatim
  from the input.
- lede: exactly two sentences on the single most important thing today.
- Summaries must be original prose that points the reader to the source. Never
  reproduce article text. Any direct quotation must be under 15 words and used only
  when the exact wording matters.
- Plain text only. No emojis anywhere. Never use em dashes; use commas, colons, or
  separate sentences instead.
"""


class SummarizeError(Exception):
    pass


def build_user_prompt(stories: list[Story], interests: str) -> str:
    payload = [
        {
            "rank": i + 1,
            "title": s.entry.title,
            "source": s.entry.source,
            "url": s.entry.canonical_url or s.entry.raw_url,
            "related_urls": [e.canonical_url or e.raw_url for e in s.related],
            "related_sources": [e.source for e in s.related],
            "published": s.entry.published.isoformat() if s.entry.published else None,
            "text": s.text or s.entry.feed_summary,
        }
        for i, s in enumerate(stories)
    ]
    return (
        f"Reader interest profile:\n{interests}\n\n"
        f"Candidate stories (JSON):\n{json.dumps(payload, indent=1)}"
    )


def summarize(stories: list[Story], interests: str, api_key: str) -> DigestResponse:
    """One Claude call; on a malformed response, retry once with the error
    appended, then raise SummarizeError."""
    client = anthropic.Anthropic(api_key=api_key)
    messages = [{"role": "user", "content": build_user_prompt(stories, interests)}]

    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            response = client.messages.parse(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                thinking={"type": "adaptive"},
                messages=messages,
                output_format=DigestResponse,
            )
            if response.stop_reason == "refusal":
                raise SummarizeError("model refused the request")
            if response.parsed_output is None:
                raise ValueError(f"no parsed output (stop_reason={response.stop_reason})")
            log.info(
                "summarize ok attempt=%d input_tokens=%s output_tokens=%s",
                attempt,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
            return response.parsed_output
        except SummarizeError:
            raise
        except Exception as exc:
            last_error = exc
            log.warning("summarize attempt=%d failed: %s", attempt, exc)
            if attempt == 1:
                messages = messages + [
                    {
                        "role": "user",
                        "content": (
                            "Your previous response could not be parsed against the "
                            f"required schema. Error: {exc}. Respond again with valid "
                            "JSON matching the schema exactly."
                        ),
                    }
                ]
    raise SummarizeError(f"LLM call failed twice; last error: {last_error}")


def load_fixture_response(path: Path) -> DigestResponse:
    """Canned response for --no-llm runs and tests."""
    return DigestResponse.model_validate_json(path.read_text())
