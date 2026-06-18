import asyncio
import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"

# Status codes worth retrying (transient): rate limit + server errors.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


async def _send_email(to: str, subject: str, html: str) -> bool:
    """Dispatch one email via the configured backend. Always fault-tolerant: never raises
    (callers are fire-and-forget). Returns True only on a confirmed send.

    Backends: "console" (log only), "smtp" (real, e.g. MailHog for demo), "resend" (HTTP API)."""
    backend = (settings.EMAIL_BACKEND or "console").lower()
    try:
        if backend == "smtp":
            return await _send_via_smtp(to, subject, html)
        if backend == "resend":
            return await _send_via_resend(to, subject, html)
        # console / none
        logger.info("[email:console] to=%s subject=%s (not actually sent)", to, subject)
        return False
    except Exception as exc:  # noqa: BLE001 — must never break intake
        logger.error("Email dispatch error to %s: %s", to, exc)
        return False


async def _send_via_smtp(to: str, subject: str, html: str) -> bool:
    """Send via SMTP (e.g. MailHog at smtp:1025 in docker-compose). Real, viewable email with no
    external provider — ideal for demo and testing. stdlib smtplib runs in a thread."""
    msg = EmailMessage()
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("This email requires an HTML-capable client.")
    msg.add_alternative(html, subtype="html")

    def _send() -> None:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.EMAIL_TIMEOUT_SECONDS) as s:
            s.send_message(msg)

    await asyncio.to_thread(_send)
    logger.info("[email:smtp] sent to %s via %s:%s (subject: %s)",
                to, settings.SMTP_HOST, settings.SMTP_PORT, subject)
    return True


async def _send_via_resend(to: str, subject: str, html: str) -> bool:
    """POST via the Resend API with bounded retries + backoff + per-attempt timeout."""
    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — email to %s queued-as-skipped (no-op).", to)
        return False

    payload = {
        "from": "Leads App <onboarding@resend.dev>",
        "to": [to],
        "subject": subject,
        "html": html,
    }
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    attempts = max(1, settings.EMAIL_MAX_RETRIES)
    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=settings.EMAIL_TIMEOUT_SECONDS) as client:
                response = await client.post(RESEND_API_URL, json=payload, headers=headers)
            if response.status_code in (200, 201):
                logger.info("Email sent to %s (subject: %s)", to, subject)
                return True
            if response.status_code in _RETRYABLE_STATUS and attempt < attempts:
                logger.warning(
                    "Resend transient %s for %s (attempt %d/%d) — retrying.",
                    response.status_code, to, attempt, attempts,
                )
            else:
                logger.error(
                    "Resend returned %s for email to %s: %s",
                    response.status_code, to, response.text[:300],
                )
                return False
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt >= attempts:
                logger.error("Email to %s failed after %d attempts: %s", to, attempts, exc)
                return False
            logger.warning("Network error to %s (attempt %d/%d): %s", to, attempt, attempts, exc)
        except Exception as exc:  # noqa: BLE001 — fire-and-forget must never raise
            logger.error("Unexpected error sending email to %s: %s", to, exc)
            return False

        # Exponential backoff before the next attempt: 0.5s, 1s, 2s, …
        await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

    return False


async def send_prospect_confirmation(first_name: str, last_name: str, email: str) -> None:
    """Send a confirmation email to the prospect who just submitted a lead."""
    subject = "We received your application — thank you!"
    html = f"""
    <p>Hi {first_name},</p>
    <p>Thank you for your submission. We have received your application and will review it shortly.</p>
    <p>We will be in touch with you soon.</p>
    <br>
    <p>Best regards,<br>The Team</p>
    """
    await _send_email(to=email, subject=subject, html=html)


async def send_attorney_notification(
    first_name: str, last_name: str, email: str
) -> None:
    """Notify the attorney that a new lead has been submitted."""
    subject = f"New lead received: {first_name} {last_name}"
    html = f"""
    <p>A new lead has been submitted:</p>
    <ul>
        <li><strong>Name:</strong> {first_name} {last_name}</li>
        <li><strong>Email:</strong> {email}</li>
    </ul>
    <p>Please log in to the dashboard to review the application.</p>
    """
    await _send_email(to=settings.ATTORNEY_EMAIL, subject=subject, html=html)


async def send_lead_emails(first_name: str, last_name: str, email: str) -> None:
    """
    Fire both prospect confirmation and attorney notification emails.
    Errors are swallowed so as not to block the API response.
    """
    await send_prospect_confirmation(first_name, last_name, email)
    await send_attorney_notification(first_name, last_name, email)
