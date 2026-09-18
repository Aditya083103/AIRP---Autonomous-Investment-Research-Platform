# backend/services/email_service.py
"""
AIRP -- Email service (B6)

Sends the password-reset email via the Brevo transactional email API
(https://brevo.com) over plain HTTPS.

Why Brevo, not Resend (this module's previous implementation) or raw
SMTP (the one before that)
------------------------------------------------------------------------
Raw SMTP (``smtplib`` against Gmail) failed in production because
Render's free web services block all outbound traffic to SMTP ports --
see git history for that fix's own reasoning. Switching to the Resend
HTTP API fixed that, but Resend has no way to send to an ARBITRARY
recipient without first verifying a domain you own: its only
no-domain-needed option (the shared ``onboarding@resend.dev`` sandbox
address) can only deliver to the email address that owns the Resend
account itself -- useless for a real password-reset feature, where the
recipient is whichever user requested the reset, not the developer.

Brevo supports single-SENDER verification (confirm ownership of one
plain email address via a link, e.g. a personal Gmail address) as an
alternative to full domain verification, and a sender verified this way
CAN send to any recipient -- exactly what this feature needs without
requiring the project to own a domain. The one honest tradeoff: without
domain-level SPF/DKIM alignment, deliverability to Gmail/Yahoo/Outlook
specifically is somewhat less reliable (more likely to land in spam)
than with a fully authenticated domain -- an industry-wide mail
authentication requirement since 2024, not a Brevo-specific limitation.

``httpx`` (a direct, pinned dependency since the Resend switch) makes
the POST call asynchronously -- no blocking call to offload to a worker
thread.

Whether this module is used at all is gated by
``Settings.email_service_configured`` (BREVO_API_KEY + SMTP_FROM_EMAIL
both set) -- backend.routers.auth only calls
``send_password_reset_email`` when that is True; the log-the-link-instead
fallback for an unconfigured environment lives in the router itself, not
here, since "no email service configured" is a caller-level branch, not
a failure this module needs to represent.

Never raises to its caller: a Brevo API failure (bad API key, unverified
sender, network error) is logged and swallowed, matching
POST /auth/password-reset/request's own "always return 200" contract
(backend/routers/auth.py's own docstring) -- a transient email-sending
failure must not turn into a 500 that also happens to leak "yes, that
email exists" through the different response shape/timing of a crash
vs. a clean 200.

Public API
----------
    from backend.services.email_service import send_password_reset_email
"""

import logging
from typing import Any

import httpx

from backend.config import Settings

logger = logging.getLogger(__name__)

__all__ = ["send_password_reset_email"]

#: Brevo's single transactional-email-sending endpoint --
#: https://developers.brevo.com/reference/sendtransacemail
_BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

#: Sender display name attached to the verified SMTP_FROM_EMAIL address.
_SENDER_NAME = "AIRP"

#: Request timeout (seconds) -- a hung/slow Brevo API call must not hang
#: the request handler indefinitely.
_REQUEST_TIMEOUT_SECONDS = 10.0


def _build_email_payload(
    *, to_email: str, from_email: str, reset_url: str
) -> dict[str, Any]:
    return {
        "sender": {"email": from_email, "name": _SENDER_NAME},
        "to": [{"email": to_email}],
        "subject": "Reset your AIRP password",
        "textContent": (
            "We received a request to reset your AIRP password.\n\n"
            f"Reset it here: {reset_url}\n\n"
            "This link expires soon and can only be used once. If you did "
            "not request this, you can safely ignore this email -- your "
            "password will not be changed."
        ),
    }


async def send_password_reset_email(
    *, settings: Settings, to_email: str, reset_url: str
) -> bool:
    """
    Send the password-reset email via the Brevo API. Returns True on
    success, False on any failure (logged, never raised) -- the caller
    (backend.routers.auth) treats either outcome identically for the
    HTTP response (always 200), but can use the return value for its
    own logging/observability.

    Caller is responsible for checking ``settings.email_service_configured``
    first -- this function does not check it itself and will send an
    unauthenticated request (Brevo will reject it with 401) against an
    empty ``brevo_api_key``.
    """
    payload = _build_email_payload(
        to_email=to_email,
        from_email=settings.smtp_from_email,
        reset_url=reset_url,
    )

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _BREVO_API_URL,
                json=payload,
                headers={
                    "api-key": settings.brevo_api_key,
                    "Accept": "application/json",
                },
            )
    except httpx.HTTPError:
        logger.exception(
            "email_service: could not reach the Brevo API to send a "
            "password-reset email to %s",
            to_email,
        )
        return False

    if response.status_code >= 400:
        # Logged with the response body (not just the status code) --
        # Brevo's error responses name the actual problem (e.g. an
        # unverified sender, an invalid/revoked API key) directly, which
        # a bare "it failed" log would hide.
        logger.error(
            "email_service: Brevo API rejected the password-reset email "
            "to %s (status=%d): %s",
            to_email,
            response.status_code,
            response.text,
        )
        return False

    return True
