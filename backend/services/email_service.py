# backend/services/email_service.py
"""
AIRP -- Email service (B6)

Sends the password-reset email over SMTP using only the Python standard
library (``smtplib`` + ``email.message.EmailMessage``) -- no new
third-party dependency (e.g. ``aiosmtplib``) was added, since this
project's other tasks have consistently avoided installing packages
against a registry the build/dev environment cannot reach to verify
(see frontend/src/components/analysis/CompanyAutocomplete.tsx's own
docstring for the identical constraint on the frontend side).
``smtplib``'s calls are blocking, so ``send_password_reset_email``
offloads the actual connect/send to a worker thread via
``asyncio.to_thread`` -- the same pattern
backend.services.analysis._invoke_graph_sync (and every yfinance tool
call in backend/tools/) already uses for blocking I/O inside an async
FastAPI route.

Whether this module is used at all is gated by
``Settings.email_service_configured`` (SMTP_HOST + SMTP_FROM_EMAIL both
set) -- backend.routers.auth only calls ``send_password_reset_email``
when that is True; the log-the-link-instead fallback for an
unconfigured environment lives in the router itself, not here, since
"no email service configured" is a caller-level branch, not a failure
this module needs to represent.

Never raises to its caller: an SMTP failure (bad credentials, relay
down, network error) is logged and swallowed, matching
POST /auth/password-reset/request's own "always return 200" contract
(backend/routers/auth.py's own docstring) -- a transient email-sending
failure must not turn into a 500 that also happens to leak "yes, that
email exists" through the different response shape/timing of a crash
vs. a clean 200.

Public API
----------
    from backend.services.email_service import send_password_reset_email
"""

import asyncio
from email.message import EmailMessage
import logging
import smtplib
import socket

from backend.config import Settings

logger = logging.getLogger(__name__)

__all__ = ["send_password_reset_email"]

#: Connection/send timeout (seconds) -- a hung SMTP relay must not hang
#: the request handler indefinitely (this runs in a worker thread via
#: asyncio.to_thread, but a request handler awaiting it would still
#: stall until this returns).
_SMTP_TIMEOUT_SECONDS = 10


class _IPv4SMTP(smtplib.SMTP):
    """
    ``smtplib.SMTP`` that always connects over IPv4.

    Bug fix: on Render (and other containerised hosts with an IPv6
    address assigned but no functional outbound IPv6 route),
    ``smtplib``'s default ``_get_socket`` hands the hostname straight to
    ``socket.create_connection``, which tries whatever
    ``getaddrinfo(host)`` returns FIRST -- Gmail's SMTP servers publish
    both an A (IPv4) and AAAA (IPv6) record, and on exactly such a host
    the IPv6 attempt fails immediately with
    ``OSError: [Errno 101] Network is unreachable`` (a routing failure,
    not a firewall block -- there is no fallback to the working IPv4
    address). Reproduced live via Render's own deployment logs.

    Resolving to an IPv4 address ourselves and connecting to THAT
    sidesteps the broken IPv6 path entirely. This does NOT break TLS:
    ``smtplib.SMTP.connect`` sets ``self._host`` to the ORIGINAL
    hostname argument before ``_get_socket`` ever runs, and
    ``starttls()`` verifies the server's certificate against
    ``self._host`` (``server_hostname=self._host``), not against
    whatever address the socket actually connected to -- so certificate
    validation still correctly checks the hostname, e.g. "smtp.gmail.com",
    exactly as if no override existed here.
    """

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        ipv4_address = socket.gethostbyname(host)
        return socket.create_connection(
            (ipv4_address, port), timeout, self.source_address
        )


def _build_message(*, to_email: str, from_email: str, reset_url: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Reset your AIRP password"
    message["From"] = from_email
    message["To"] = to_email
    message.set_content(
        "We received a request to reset your AIRP password.\n\n"
        f"Reset it here: {reset_url}\n\n"
        "This link expires soon and can only be used once. If you did "
        "not request this, you can safely ignore this email -- your "
        "password will not be changed."
    )
    return message


def _send_sync(*, settings: Settings, to_email: str, reset_url: str) -> None:
    """Blocking SMTP send -- always call via asyncio.to_thread, never
    directly from async code."""
    message = _build_message(
        to_email=to_email,
        from_email=settings.smtp_from_email,
        reset_url=reset_url,
    )
    with _IPv4SMTP(
        settings.smtp_host, settings.smtp_port, timeout=_SMTP_TIMEOUT_SECONDS
    ) as client:
        if settings.smtp_use_tls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)


async def send_password_reset_email(
    *, settings: Settings, to_email: str, reset_url: str
) -> bool:
    """
    Send the password-reset email. Returns True on success, False on
    any failure (logged, never raised) -- the caller
    (backend.routers.auth) treats either outcome identically for the
    HTTP response (always 200), but can use the return value for its
    own logging/observability.

    Caller is responsible for checking ``settings.email_service_configured``
    first -- this function does not check it itself and will raise an
    ``smtplib`` connection error against an empty ``smtp_host``.
    """
    try:
        await asyncio.to_thread(
            _send_sync, settings=settings, to_email=to_email, reset_url=reset_url
        )
        return True
    except Exception:
        logger.exception(
            "email_service: failed to send password-reset email to %s", to_email
        )
        return False
