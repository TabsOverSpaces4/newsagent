"""Entrypoint: python -m digest

Runs the pipeline stages in order and logs a structured count line per stage,
so the Actions log alone shows where a run went wrong.

Exit codes:
  0 success (including clean exit when today's digest was already sent)
  2 too many feed failures
  3 too few stories survived ranking
  4 LLM failed twice
  5 send error
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime

from . import dedupe, enrich, ingest, rank, render, send, state, summarize
from .config import ROOT, load_settings
from .ingest import USER_AGENT, TooManyFeedFailures

log = logging.getLogger("digest")

EXIT_OK = 0
EXIT_FEEDS = 2
EXIT_TOO_FEW_STORIES = 3
EXIT_LLM = 4
EXIT_SEND = 5

FIXTURE_RESPONSE = ROOT / "tests" / "fixtures" / "llm_response.json"
OUT_DIR = ROOT / "out"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m digest")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run the full pipeline but write out/preview.html instead of sending"
        " (automatic when RESEND_API_KEY is unset)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="use the canned fixture response instead of calling Claude",
    )
    parser.add_argument("--limit", type=int, metavar="N", help="cap stories for fast iteration")
    parser.add_argument("--force", action="store_true", help="bypass the already-sent check")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s %(message)s", stream=sys.stdout
    )
    args = parse_args(argv)
    settings = load_settings()
    run_date = datetime.now(UTC).date().isoformat()
    conn = state.connect(settings.db_path)

    dry_run = args.dry_run or not settings.resend_api_key
    if dry_run and not args.dry_run:
        log.info("RESEND_API_KEY unset; running in dry-run mode")

    if not dry_run and not args.force and state.already_sent(conn, run_date):
        log.info("stage=guard run_date=%s already sent; exiting cleanly", run_date)
        return EXIT_OK
    if not dry_run and not settings.recipients:
        log.error("stage=guard no recipients configured (set RECIPIENTS)")
        return EXIT_SEND

    # 1. Ingest
    try:
        entries, feeds_failed = asyncio.run(
            ingest.ingest(
                settings.feeds,
                window_hours=settings.window_hours,
                max_failure_ratio=settings.max_feed_failure_ratio,
            )
        )
    except TooManyFeedFailures as exc:
        log.error("stage=ingest fatal: %s", exc)
        state.mark_failed(conn, run_date, str(exc))
        return EXIT_FEEDS
    log.info(
        "stage=ingest feeds=%d feeds_failed=%d entries=%d",
        len(settings.feeds),
        feeds_failed,
        len(entries),
    )

    # 2. Canonicalize + dedupe
    asyncio.run(dedupe.resolve_redirects(entries, USER_AGENT))
    fresh = dedupe.filter_new(entries, conn)
    log.info("stage=urldedupe fresh=%d already_seen=%d", len(fresh), len(entries) - len(fresh))

    from .embeddings import embed  # deferred: loads the model

    stories = (
        dedupe.cluster(fresh, embed([e.title for e in fresh]), threshold=settings.dedupe_threshold)
        if fresh
        else []
    )
    log.info("stage=cluster stories=%d merged=%d", len(stories), len(fresh) - len(stories))

    # 3. Rank
    kept: list = []
    if stories:
        interest_vec = embed([settings.interests])[0]
        story_vecs = embed([rank.ranking_text(s) for s in stories])
        kept, dropped = rank.rank(stories, story_vecs, interest_vec, top_n=settings.top_n)
        log.info("stage=rank kept=%d dropped=%d", len(kept), len(dropped))

    if len(kept) < settings.min_stories:
        log.error(
            "stage=rank fatal: only %d stories survived (need %d); refusing to send a thin digest",
            len(kept),
            settings.min_stories,
        )
        state.mark_failed(conn, run_date, f"only {len(kept)} stories")
        return EXIT_TOO_FEW_STORIES

    if args.limit:
        kept = kept[: args.limit]
        log.info("stage=limit kept=%d", len(kept))

    # 4. Enrich
    enriched = asyncio.run(enrich.enrich(kept, USER_AGENT, max_words=settings.max_article_words))
    log.info("stage=enrich ok=%d skipped=%d", enriched, len(kept) - enriched)

    # 5. Summarize
    if args.no_llm:
        digest_response = summarize.load_fixture_response(FIXTURE_RESPONSE)
        log.info("stage=summarize fixture=%s", FIXTURE_RESPONSE.name)
    else:
        try:
            digest_response = summarize.summarize(
                kept, settings.interests, settings.anthropic_api_key
            )
        except summarize.SummarizeError as exc:
            log.error("stage=summarize fatal: %s", exc)
            state.mark_failed(conn, run_date, str(exc))
            return EXIT_LLM
    story_count = sum(len(sec.stories) for sec in digest_response.sections)
    log.info(
        "stage=summarize sections=%d stories=%d",
        len(digest_response.sections),
        story_count,
    )

    # 6. Render
    html, text = render.render(digest_response, run_date)
    subject = render.subject_line(run_date)
    log.info("stage=render html_bytes=%d text_bytes=%d", len(html), len(text))

    if dry_run:
        OUT_DIR.mkdir(exist_ok=True)
        (OUT_DIR / "preview.html").write_text(html)
        (OUT_DIR / "preview.txt").write_text(text)
        log.info("stage=send dry_run=1 wrote out/preview.html (nothing sent, no state written)")
        return EXIT_OK

    # 7. Send. Marker goes in BEFORE the API call so a same-day retry can
    # never double-send; see state.py for the tradeoff.
    state.mark_sending(conn, run_date, story_count)
    try:
        send.send_digest(
            api_key=settings.resend_api_key,
            from_email=settings.from_email,
            reply_to=settings.reply_to,
            recipients=settings.recipients,
            subject=subject,
            html=html,
            text=text,
        )
    except send.SendError as exc:
        log.error("stage=send fatal: %s (marker kept; use --force to resend today)", exc)
        return EXIT_SEND
    state.mark_sent(conn, run_date)
    log.info("stage=send recipients=%d subject=%r", len(settings.recipients), subject)

    # 8. Persist state: everything considered this run is now seen.
    state.mark_seen(conn, fresh)
    pruned = state.prune_seen(conn, days=30)
    log.info("stage=state seen_added=%d pruned=%d", len(fresh), pruned)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
