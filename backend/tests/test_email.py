"""Verify that submitting a lead emails BOTH the prospect and the attorney.

The Resend HTTP call is faked so no network/key is needed; we capture each outbound
payload and assert the two recipients, subjects, and that the prospect's name is included.
"""

import pytest

from app.services import email as email_svc

pytestmark = pytest.mark.asyncio


class _FakeResponse:
    status_code = 200
    text = "ok"


class _CapturingClient:
    """Stand-in for httpx.AsyncClient that records every POST payload."""

    sent: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, headers=None):
        _CapturingClient.sent.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse()


async def test_lead_submission_emails_prospect_and_attorney(monkeypatch):
    _CapturingClient.sent = []
    monkeypatch.setattr(email_svc.settings, "EMAIL_BACKEND", "resend")
    monkeypatch.setattr(email_svc.settings, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(email_svc.settings, "ATTORNEY_EMAIL", "attorney@company.com")
    monkeypatch.setattr(email_svc.httpx, "AsyncClient", _CapturingClient)

    await email_svc.send_lead_emails(
        first_name="Riddhi", last_name="Shah", email="vsriddhi@gmail.com"
    )

    sent = _CapturingClient.sent
    assert len(sent) == 2, f"expected 2 emails (prospect + attorney), got {len(sent)}"

    recipients = [m["json"]["to"][0] for m in sent]
    assert "vsriddhi@gmail.com" in recipients, "prospect not emailed"
    assert "attorney@company.com" in recipients, "attorney not emailed"

    # Each call authenticates with the API key and targets the Resend endpoint.
    for m in sent:
        assert m["url"] == email_svc.RESEND_API_URL
        assert m["headers"]["Authorization"] == "Bearer re_test_key"

    # The attorney notification names the prospect; the prospect mail greets them.
    by_to = {m["json"]["to"][0]: m["json"] for m in sent}
    assert "Riddhi" in by_to["attorney@company.com"]["subject"] + by_to["attorney@company.com"]["html"]
    assert "Riddhi" in by_to["vsriddhi@gmail.com"]["html"]


async def test_no_api_key_sends_nothing_and_does_not_raise(monkeypatch):
    """Fault-tolerant: with no key, sending is skipped silently (lead creation must not fail)."""
    _CapturingClient.sent = []
    monkeypatch.setattr(email_svc.settings, "EMAIL_BACKEND", "resend")
    monkeypatch.setattr(email_svc.settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(email_svc.httpx, "AsyncClient", _CapturingClient)

    await email_svc.send_lead_emails(first_name="A", last_name="B", email="a@b.com")

    assert _CapturingClient.sent == []  # no HTTP attempted, no exception


class _FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def send_message(self, msg):
        _FakeSMTP.sent.append({"to": msg["To"], "subject": msg["Subject"], "from": msg["From"]})


async def test_smtp_backend_sends_both(monkeypatch):
    """The SMTP backend (e.g. MailHog for demo) actually delivers both emails."""
    _FakeSMTP.sent = []
    monkeypatch.setattr(email_svc.settings, "EMAIL_BACKEND", "smtp")
    monkeypatch.setattr(email_svc.settings, "ATTORNEY_EMAIL", "attorney@company.com")
    monkeypatch.setattr(email_svc.smtplib, "SMTP", _FakeSMTP)

    await email_svc.send_lead_emails(first_name="Riddhi", last_name="Shah", email="p@x.com")

    tos = [m["to"] for m in _FakeSMTP.sent]
    assert "p@x.com" in tos and "attorney@company.com" in tos
    assert len(_FakeSMTP.sent) == 2
