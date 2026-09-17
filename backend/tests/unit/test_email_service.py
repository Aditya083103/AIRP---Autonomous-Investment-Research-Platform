# backend/tests/unit/test_email_service.py
"""
Unit tests for B6: backend/services/email_service.py

backend.services.email_service._send_sync (the actual smtplib call) is
patched at module scope via unittest.mock.patch -- there is no real SMTP
server in this test environment, and this module deliberately keeps the
blocking smtplib logic in one small, directly-testable sync function
for exactly this reason (see that function's own docstring).

Test strategy
-------------
send_password_reset_email
    success -- returns True, forwards to, from, and the reset URL
    failure (smtplib raises) -- returns False, never re-raises
    runs the blocking call off the event loop (via asyncio.to_thread) --
        verified indirectly by confirming the async call still resolves
        when the underlying sync call is a plain (non-async) function,
        which would deadlock/type-error if awaited directly instead

ENVIRONMENT must be set to 'test' before any backend import.
"""

from __future__ import annotations

import os
from typing import Any, cast

os.environ.setdefault("ENVIRONMENT", "test")

from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402

from backend.config import Settings  # noqa: E402
from backend.services.email_service import send_password_reset_email  # noqa: E402


def _make_settings(
    smtp_username: str = "airp",
    smtp_password: str = "secret",
    smtp_use_tls: bool = True,
) -> Settings:
    return Settings.model_construct(
        environment="test",
        database_url="x",
        secret_key="a" * 32,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        smtp_from_email="noreply@airp.example.com",
        smtp_use_tls=smtp_use_tls,
    )


class TestSendPasswordResetEmailSuccess:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self) -> None:
        with patch("backend.services.email_service._send_sync") as mock_send:
            result = await send_password_reset_email(
                settings=_make_settings(),
                to_email="user@example.com",
                reset_url="https://airp.example.com/reset-password?token=abc",
            )
        assert result is True
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_forwards_settings_to_email_and_reset_url(self) -> None:
        settings = _make_settings()
        with patch("backend.services.email_service._send_sync") as mock_send:
            await send_password_reset_email(
                settings=settings,
                to_email="user@example.com",
                reset_url="https://airp.example.com/reset-password?token=abc",
            )
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["settings"] is settings
        assert call_kwargs["to_email"] == "user@example.com"
        assert (
            call_kwargs["reset_url"]
            == "https://airp.example.com/reset-password?token=abc"
        )


class TestSendPasswordResetEmailFailure:
    @pytest.mark.asyncio
    async def test_returns_false_when_smtp_raises_never_reraises(self) -> None:
        with patch(
            "backend.services.email_service._send_sync",
            side_effect=OSError("connection refused"),
        ):
            result = await send_password_reset_email(
                settings=_make_settings(),
                to_email="user@example.com",
                reset_url="https://airp.example.com/reset-password?token=abc",
            )
        assert result is False


class TestBuildMessage:
    def test_message_contains_the_reset_url_and_correct_headers(self) -> None:
        from backend.services.email_service import _build_message

        message = _build_message(
            to_email="user@example.com",
            from_email="noreply@airp.example.com",
            reset_url="https://airp.example.com/reset-password?token=abc123",
        )
        assert message["To"] == "user@example.com"
        assert message["From"] == "noreply@airp.example.com"
        assert (
            "https://airp.example.com/reset-password?token=abc123"
            in message.get_content()
        )


class TestSendSync:
    def test_starts_tls_when_configured(self) -> None:
        settings = _make_settings(smtp_use_tls=True)
        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)

        with patch(
            "backend.services.email_service._IPv4SMTP", return_value=fake_client
        ) as mock_smtp:
            from backend.services.email_service import _send_sync

            _send_sync(
                settings=settings,
                to_email="user@example.com",
                reset_url="https://airp.example.com/reset-password?token=abc",
            )

        mock_smtp.assert_called_once_with(
            settings.smtp_host, settings.smtp_port, timeout=10
        )
        fake_client.starttls.assert_called_once()
        fake_client.login.assert_called_once_with(
            settings.smtp_username, settings.smtp_password
        )
        fake_client.send_message.assert_called_once()

    def test_skips_login_when_no_username_configured(self) -> None:
        settings = _make_settings(smtp_username="", smtp_password="")
        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)

        with patch(
            "backend.services.email_service._IPv4SMTP", return_value=fake_client
        ):
            from backend.services.email_service import _send_sync

            _send_sync(
                settings=settings,
                to_email="user@example.com",
                reset_url="https://airp.example.com/reset-password?token=abc",
            )

        fake_client.login.assert_not_called()

    def test_skips_starttls_when_disabled(self) -> None:
        settings = _make_settings(smtp_use_tls=False)
        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)

        with patch(
            "backend.services.email_service._IPv4SMTP", return_value=fake_client
        ):
            from backend.services.email_service import _send_sync

            _send_sync(
                settings=settings,
                to_email="user@example.com",
                reset_url="https://airp.example.com/reset-password?token=abc",
            )

        fake_client.starttls.assert_not_called()


class TestIPv4SMTP:
    """
    Regression tests for the Render "Network is unreachable" bug: Gmail's
    SMTP servers publish both an A and AAAA record, and smtplib's default
    socket resolution tries whichever getaddrinfo() returns first -- IPv6
    on a host with no working outbound IPv6 route. _IPv4SMTP forces the
    actual TCP connection to the resolved IPv4 address while leaving the
    hostname used for TLS certificate verification untouched.
    """

    def test_get_socket_connects_to_the_resolved_ipv4_address(self) -> None:
        from backend.services.email_service import _IPv4SMTP

        client = _IPv4SMTP.__new__(_IPv4SMTP)
        client.source_address = None

        with (
            patch("socket.gethostbyname", return_value="93.184.216.34") as mock_resolve,
            patch("socket.create_connection") as mock_connect,
        ):
            client._get_socket("smtp.gmail.com", 587, 10)

        mock_resolve.assert_called_once_with("smtp.gmail.com")
        mock_connect.assert_called_once_with(("93.184.216.34", 587), 10, None)

    def test_host_used_for_tls_verification_is_untouched(self) -> None:
        """
        connect() (smtplib.SMTP's own, not overridden here) sets
        self._host to the ORIGINAL hostname before _get_socket runs, and
        starttls() later verifies the server certificate against
        self._host -- confirming _get_socket resolving to an IP for the
        socket itself has no effect on what starttls() checks against.
        """
        from backend.services.email_service import _IPv4SMTP

        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("socket.create_connection"),
            patch.object(_IPv4SMTP, "getreply", return_value=(220, b"ok")),
        ):
            client = _IPv4SMTP("smtp.gmail.com", 587, timeout=10)

        # _host is set by smtplib.SMTP's own connect(), not declared in
        # its type stubs -- cast(Any, ...) (not a bare type: ignore)
        # keeps this strict-mypy-clean.
        assert cast(Any, client)._host == "smtp.gmail.com"
