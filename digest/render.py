"""Stage 6: render the digest to HTML and plaintext via jinja2.

Also the safety net for the no-em-dash / no-emoji rules: every text field of
the LLM response is scrubbed before it reaches a template.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .models import DigestResponse

TEMPLATE_DIR = Path(__file__).parent / "templates"

_EM_DASH_RE = re.compile(r"\s*—+\s*")  # em dash, with surrounding spaces
_EMOJI_RE = re.compile(
    "["
    "\U0001f000-\U0001faff"  # emoji and symbol blocks
    "☀-➿"  # misc symbols, dingbats
    "\U0001f1e6-\U0001f1ff"  # regional indicators (flags)
    "⬀-⯿"  # arrows/symbols block used by some emoji
    "️"  # variation selector
    "‍"  # zero-width joiner
    "]"
)

_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=lambda name: bool(name) and name.endswith("html.j2"),
    trim_blocks=True,
    lstrip_blocks=True,
)


def scrub(text: str) -> str:
    """Replace em dashes with ', ' and remove emoji."""
    text = _EM_DASH_RE.sub(", ", text)
    return _EMOJI_RE.sub("", text).strip()


def clean_digest(digest: DigestResponse) -> DigestResponse:
    digest = digest.model_copy(deep=True)
    digest.lede = scrub(digest.lede)
    for section in digest.sections:
        section.title = scrub(section.title)
        for story in section.stories:
            story.headline = scrub(story.headline)
            story.summary = scrub(story.summary)
            story.why_it_matters = scrub(story.why_it_matters)
    return digest


def generate_story_id(url: str, run_date: str) -> str:
    """SHA-256 of url + run_date, truncated to 12 hex chars."""
    return hashlib.sha256(f"{url}{run_date}".encode()).hexdigest()[:12]


def generate_hmac(story_id: str, score: int, secret: str) -> str:
    """HMAC-SHA256 over story_id + score, returned as hex."""
    return hmac_mod.new(
        secret.encode(), f"{story_id}{score}".encode(), hashlib.sha256,
    ).hexdigest()


def render(
    digest: DigestResponse,
    run_date: str,
    worker_url: str = "",
    hmac_secret: str = "",
) -> tuple[str, str]:
    """Returns (html, plaintext) for the email."""
    digest = clean_digest(digest)
    ctx: dict = {"digest": digest, "run_date": run_date, "worker_url": worker_url}

    if worker_url and hmac_secret:
        scores = [0, 4, 7, 10]
        story_feedback: dict[str, dict] = {}
        for section in digest.sections:
            for story in section.stories:
                sid = generate_story_id(story.url, run_date)
                story_feedback[story.url] = {
                    "sid": sid,
                    "hmacs": {s: generate_hmac(sid, s, hmac_secret) for s in scores},
                }
        ctx["story_feedback"] = story_feedback
        ctx["rating_scores"] = scores

    html = _env.get_template("digest.html.j2").render(**ctx)
    text = _env.get_template("digest.txt.j2").render(**ctx)
    return html, text


def subject_line(run_date: str) -> str:
    return f"RFA Chip Digest {run_date}"
