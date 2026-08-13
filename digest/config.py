"""Configuration loading: config/ files plus environment variables.

Recipients intentionally come from the RECIPIENTS env var (or a gitignored
config/recipients.yaml for local runs) because the repo is public.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .models import Feed

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseModel):
    feeds: list[Feed]
    interests: str
    recipients: list[str]
    from_email: str = ""
    reply_to: str = ""
    anthropic_api_key: str = ""
    resend_api_key: str = ""
    window_hours: int = 48
    dedupe_threshold: float = 0.85
    top_n: int = 50
    max_article_words: int = 3000
    max_feed_failure_ratio: float = 0.4
    min_stories: int = 5
    db_path: Path = Field(default=ROOT / "state" / "digest.db")
    feedback_worker_url: str = ""
    feedback_hmac_secret: str = ""
    feedback_export_secret: str = ""


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader; real environment variables always win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def load_settings(config_dir: Path = ROOT / "config") -> Settings:
    load_dotenv()
    feeds_raw = yaml.safe_load((config_dir / "feeds.yaml").read_text())
    feeds = [Feed(**f) for f in feeds_raw["feeds"]]
    interests = (config_dir / "interests.md").read_text().strip()
    return Settings(
        feeds=feeds,
        interests=interests,
        recipients=_load_recipients(config_dir),
        from_email=os.environ.get("FROM_EMAIL", ""),
        reply_to=os.environ.get("REPLY_TO", ""),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        resend_api_key=os.environ.get("RESEND_API_KEY", ""),
        feedback_worker_url=os.environ.get("FEEDBACK_WORKER_URL", ""),
        feedback_hmac_secret=os.environ.get("FEEDBACK_HMAC_SECRET", ""),
        feedback_export_secret=os.environ.get("FEEDBACK_EXPORT_SECRET", ""),
    )


def _load_recipients(config_dir: Path) -> list[str]:
    env = os.environ.get("RECIPIENTS", "")
    if env.strip():
        return [r.strip() for r in env.split(",") if r.strip()]
    local = config_dir / "recipients.yaml"
    if local.exists():
        data = yaml.safe_load(local.read_text()) or {}
        return list(data.get("recipients", []))
    return []
