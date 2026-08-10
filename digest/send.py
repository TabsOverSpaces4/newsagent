"""Stage 7: deliver via Resend.

One send per recipient (never a visible multi-recipient To: header). The
sent marker is written by the caller BEFORE this runs; see state.py.
"""

from __future__ import annotations

import logging

import resend

log = logging.getLogger(__name__)


class SendError(Exception):
    pass


def send_digest(
    api_key: str,
    from_email: str,
    reply_to: str,
    recipients: list[str],
    subject: str,
    html: str,
    text: str,
) -> None:
    """Send individually to each recipient. Any failure raises SendError,
    after attempting the remaining recipients."""
    resend.api_key = api_key
    failures: list[str] = []
    for recipient in recipients:
        try:
            resend.Emails.send(
                {
                    "from": from_email,
                    "to": [recipient],
                    "reply_to": reply_to or from_email,
                    "subject": subject,
                    "html": html,
                    "text": text,
                }
            )
            log.info("sent to=%s", recipient)
        except Exception as exc:
            log.error("send failed to=%s error=%s", recipient, exc)
            failures.append(recipient)
    if failures:
        raise SendError(f"send failed for {len(failures)}/{len(recipients)}: {failures}")
