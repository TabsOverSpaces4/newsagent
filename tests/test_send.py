import pytest
import resend

from digest.send import SendError, send_digest


def test_sends_individually_with_reply_to(monkeypatch):
    sent = []
    monkeypatch.setattr(resend.Emails, "send", lambda params: sent.append(params) or {"id": "x"})
    send_digest(
        api_key="k",
        from_email="digest@example.com",
        reply_to="me@example.com",
        recipients=["a@example.com", "b@example.com"],
        subject="Chip Digest 2026-08-10",
        html="<p>hi</p>",
        text="hi",
    )
    assert len(sent) == 2
    # One recipient per send; never a shared To: header.
    assert [p["to"] for p in sent] == [["a@example.com"], ["b@example.com"]]
    assert all(p["reply_to"] == "me@example.com" for p in sent)
    assert all(p["from"] == "digest@example.com" for p in sent)


def test_reply_to_defaults_to_from(monkeypatch):
    sent = []
    monkeypatch.setattr(resend.Emails, "send", lambda params: sent.append(params) or {"id": "x"})
    send_digest(
        api_key="k",
        from_email="digest@example.com",
        reply_to="",
        recipients=["a@example.com"],
        subject="s",
        html="h",
        text="t",
    )
    assert sent[0]["reply_to"] == "digest@example.com"


def test_one_failure_still_attempts_rest_then_raises(monkeypatch):
    attempted = []

    def fake_send(params):
        attempted.append(params["to"][0])
        if params["to"] == ["bad@example.com"]:
            raise RuntimeError("boom")
        return {"id": "x"}

    monkeypatch.setattr(resend.Emails, "send", fake_send)
    with pytest.raises(SendError, match="1/3"):
        send_digest(
            api_key="k",
            from_email="digest@example.com",
            reply_to="",
            recipients=["a@example.com", "bad@example.com", "c@example.com"],
            subject="s",
            html="h",
            text="t",
        )
    assert attempted == ["a@example.com", "bad@example.com", "c@example.com"]
