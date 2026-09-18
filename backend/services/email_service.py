# backend/services/email_service.py
"""
AIRP -- Email service (B6)

Sends the password-reset email via the Resend transactional email API
(https://resend.com) over plain HTTPS.

Why HTTP, not raw SMTP (this module's original implementation)
------------------------------------------------------------------------
The original implementation used ``smtplib`` directly against Gmail's
SMTP relay. That worked in local development but silently failed every
time in production: Render's free web services block ALL outbound
traffic to SMTP ports (25, 465, 587) --
https://render.com/changelog/free-web-services-will-no-longer-allow-outbound-traffic-to-smtp-ports
-- so every send attempt failed with
``OSError: [Errno 101] Network is unreachable``, reproduced live against
this project's own Render deployment logs. Upgrading to a paid Render
plan would lift that block, but calling a transactional email provider's
HTTP API instead avoids the restriction entirely (port 443 is never
blocked) at no cost, and is the standard way production apps send email
from this class of host regardless.

``httpx`` (already an indirect dependency of several packages already in
requirements.txt -- FastAPI's own TestClient, and more than one LLM SDK
-- now pinned directly since this module depends on it too) makes the
POST call asynchronously, so -- unlike the old ``smtplib`` version --
there is no blocking call to offload to a worker thread via
``asyncio.to_thread``.

Whether this module is used at all is gated by
``Settings.email_service_configured`` (RESEND_API_KEY + SMTP_FROM_EMAIL
both set) -- backend.routers.auth only calls
``send_password_reset_email`` when that is True; the log-the-link-instead
fallback for an unconfigured environment lives in the router itself, not
here, since "no email service configured" is a caller-level branch, not
a failure this module needs to represent.

Never raises to its caller: a Resend API failure (bad API key,
unverified sending domain, network error) is logged and swallowed,
matching POST /auth/password-reset/request's own "always return 200"
contract (backend/routers/auth.py's own docstring) -- a transient
email-sending failure must not turn into a 500 that also happens to leak
"yes, that email exists" through the different response shape/timing of
a crash vs. a clean 200.

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

#: Resend's single email-sending endpoint --
#: https://resend.com/docs/api-reference/emails/send-email
_RESEND_API_URL = "https://api.resend.com/emails"

#: Request timeout (seconds) -- a hung/slow Resend API call must not
#: hang the request handler indefinitely.
_REQUEST_TIMEOUT_SECONDS = 10.0


def _build_email_payload(
    *, to_email: str, from_email: str, reset_url: str
) -> dict[str, Any]:
    return {
        "from": from_email,
        "to": [to_email],
        "subject": "Reset your AIRP password",
        "text": (
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
    Send the password-reset email via the Resend API. Returns True on
    success, False on any failure (logged, never raised) -- the caller
    (backend.routers.auth) treats either outcome identically for the
    HTTP response (always 200), but can use the return value for its
    own logging/observability.

    Caller is responsible for checking ``settings.email_service_configured``
    first -- this function does not check it itself and will send an
    unauthenticated request (Resend will reject it with 401) against an
    empty ``resend_api_key``.
    """
    payload = _build_email_payload(
        to_email=to_email,
        from_email=settings.smtp_from_email,
        reset_url=reset_url,
    )

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _RESEND_API_URL,
                json=payload,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            )
    except httpx.HTTPError:
        logger.exception(
            "email_service: could not reach the Resend API to send a "
            "password-reset email to %s",
            to_email,
        )
        return False

    if response.status_code >= 400:
        # Logged with the response body (not just the status code) --
        # Resend's error responses name the actual problem (e.g. "The
        # gmail.com domain is not verified", an invalid/revoked API
        # key) directly, which a bare "it failed" log would hide.
        logger.error(
            "email_service: Resend API rejected the password-reset email "
            "to %s (status=%d): %s",
            to_email,
            response.status_code,
            response.text,
        )
        return False

    return True
