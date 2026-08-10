# newsagent

A self-contained daily email digest of semiconductor industry news, with emphasis
on analog/RF/mixed-signal design, AI hardware, and AI applied to chip design (EDA).
Runs unattended on GitHub Actions cron and emails a small fixed recipient list.

## How it works

```
feeds.yaml -> ingest -> canonicalize/dedupe -> rank -> enrich -> summarize -> render -> send
                (48h window)   (seen table +      (interest    (trafilatura)  (one Claude   (jinja2)   (Resend)
                               title clustering)   profile)                     call)
```

- **Dedupe** is two-level: exact canonical-URL hashing against a SQLite `seen`
  table, then story-level clustering of near-duplicate headlines using local
  sentence-transformers embeddings (`all-MiniLM-L6-v2`, no API key needed).
- **Ranking** scores each story by cosine similarity between its title/summary
  and `config/interests.md`, scaled by the feed's `weight`.
- **Summarize** is a single Claude call (`claude-opus-4-8`) with a structured
  output schema; malformed responses retry once with the parse error appended.
- **State** lives in `state/digest.db`, committed back to the repo by the
  workflow after each run (this also keeps the cron schedule alive against
  GitHub's 60-day inactivity rule).

## Setup

### Local

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env        # fill in keys; .env is gitignored
```

(Plain `python3.12 -m venv .venv && pip install -r requirements.txt` works too.)

### GitHub

Push to a GitHub repo (default branch `main`), then add repository secrets under
Settings -> Secrets and variables -> Actions:

| Secret | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude summarization |
| `RESEND_API_KEY` | Email delivery |
| `RECIPIENTS` | Comma-separated recipient emails |
| `FROM_EMAIL` | Sender, on a Resend-verified domain |
| `REPLY_TO` | Reply-to address |

The recipient list and addresses are secrets (not files) because this repo is
public. Note that `config/interests.md` and `state/digest.db` (seen-URL history)
are world-readable; don't put anything sensitive in them.

The workflow (`.github/workflows/daily.yml`) runs at **15:07 UTC**, which is
8:07am PDT. GitHub cron is fixed to UTC, so in winter it arrives at 7:07am PST;
edit the cron line if that bothers you. Use the **Run workflow** button
(workflow_dispatch) for manual runs; it has `dry_run` and `force` checkboxes.

## Running a dry run

```sh
.venv/bin/python -m digest --no-llm --limit 10   # free: canned LLM response
.venv/bin/python -m digest --dry-run             # real Claude call, no email
open out/preview.html
```

- `--dry-run` runs the whole pipeline but writes `out/preview.html` /
  `preview.txt` instead of sending. It is automatic whenever `RESEND_API_KEY`
  is unset, and it never writes state (no seen-URLs, no run marker).
- `--no-llm` substitutes `tests/fixtures/llm_response.json` so you can iterate
  on templates for free.
- `--limit N` caps stories for fast iteration.
- `--force` bypasses the already-sent-today guard (e.g. to resend after a
  partial failure).

## Adding a feed

Append to `config/feeds.yaml`:

```yaml
  - name: My New Source
    url: https://example.com/feed.xml
    weight: 1.2   # optional; >1 boosts ranking and cluster representative choice
```

Then `.venv/bin/python -m digest --no-llm` to confirm the feed parses (look for
`feed ok name='My New Source'` in the log). A feed that 404s or times out is
logged and skipped; the run only fails if more than 40% of feeds fail.

## Failure model

The run exits non-zero (and the Actions run goes red) when:

| Exit code | Meaning |
|---|---|
| 2 | More than 40% of feeds failed |
| 3 | Fewer than 5 stories survived ranking (refuses to send a thin digest) |
| 4 | The Claude call failed twice |
| 5 | Send error, or no recipients configured |

A single bad feed, paywalled article, or unparseable entry never aborts the run.
The `sent_YYYY-MM-DD` marker is written *before* the send call, so a same-day
retry exits cleanly rather than double-sending; if a run died between marker and
delivery, re-run with `--force`.

Debugging at 7am: the Actions log has one `stage=... counts` line per stage
(ingest, urldedupe, cluster, rank, enrich, summarize, render, send, state);
the first stage whose counts look wrong is where to start.

## Rotating keys

1. Create the new key (Anthropic console / Resend dashboard).
2. Update the repository secret (`ANTHROPIC_API_KEY` or `RESEND_API_KEY`) —
   Settings -> Secrets and variables -> Actions -> edit.
3. Revoke the old key at the provider.
4. Trigger a `workflow_dispatch` dry run to confirm, then delete any local
   copies in `.env`.

Keys are never printed by the code, not even truncated.

## Tests

```sh
.venv/bin/python -m pytest        # no network, no model download
.venv/bin/ruff check . && .venv/bin/ruff format --check .
DIGEST_MODEL_TESTS=1 .venv/bin/python -m pytest tests/test_dedupe.py  # opt-in: real embeddings
```
