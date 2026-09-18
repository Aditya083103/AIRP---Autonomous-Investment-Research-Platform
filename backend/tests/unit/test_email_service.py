# backend/tests/unit/test_email_service.py
"""
Unit tests for B6: backend/services/email_service.py

backend.services.email_service.httpx.AsyncClient (the actual Brevo API
call) is patched at module scope via unittest.mock.patch -- there is no
real network access in this test environment.

Test strategy
-------------
send_password_reset_email
    success -- returns True, posts the correct payload/auth header
    Brevo rejects the request (4xx/5xx) -- returns False, never raises
    network error (httpx raises) -- returns False, never raises
_build_email_payload
    correct sender/to/subject, reset URL present in the text body

ENVIRONMENT must be set to 'test' before any backend import.
"""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402

from backend.config import Settings  # noqa: E402
from backend.services.email_service import send_password_reset_email  # noqa: E402


def _make_settings(brevo_api_key: str = "test-brevo-key") -> Settings:
    return Settings.model_construct(
        environment="test",
        database_url="x",
        secret_key="a" * 32,
        brevo_api_key=brevo_api_key,
        smtp_from_email="noreply@airp.example.com",
    )


def _make_fake_client(response: MagicMock) -> AsyncMock:
    """
    A fake `httpx.AsyncClient()` instance usable as `async with ...`,
    whose `.post(...)` resolves to `response`.
    """
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    return fake_client


class TestSendPasswordResetEmailSuccess:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self) -> None:
        response = MagicMock(status_code=201)
        fake_client = _make_fake_client(response)

        with patch(
            "backend.services.email_service.httpx.AsyncClient",
            return_value=fake_client,
        ):
            result = await send_password_reset_email(
                settings=_make_settings(),
                to_email="user@example.com",
                reset_url="https://airp.example.com/reset-password?token=abc",
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_sends_the_correct_payload_and_auth_header(self) -> None:
        settings = _make_settings(brevo_api_key="xkeysib-abc123")
        response = MagicMock(status_code=201)
        fake_client = _make_fake_client(response)

        with patch(
            "backend.services.email_service.httpx.AsyncClient",
            return_value=fake_client,
        ):
            await send_password_reset_email(
                settings=settings,
                to_email="user@example.com",
                reset_url="https://airp.example.com/reset-password?token=abc",
            )

        call_kwargs = fake_client.post.call_args.kwargs
        assert call_kwargs["headers"]["api-key"] == "xkeysib-abc123"
        body = call_kwargs["json"]
        assert body["to"] == [{"email": "user@example.com"}]
        assert body["sender"]["email"] == "noreply@airp.example.com"
        assert (
            "https://airp.example.com/reset-password?token=abc" in body["textContent"]
        )


class TestSendPasswordResetEmailFailure:
    @pytest.mark.asyncio
    async def test_returns_false_on_network_error_never_reraises(self) -> None:
        fake_client = AsyncMock()
        fake_client.post = AsyncMock(side_effect=httpx.ConnectError("boom"))
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "backend.services.email_service.httpx.AsyncClient",
            return_value=fake_client,
        ):
            result = await send_password_reset_email(
                settings=_make_settings(),
                to_email="user@example.com",
                reset_url="https://airp.example.com/reset-password?token=abc",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_brevo_rejects_the_request(self) -> None:
        """E.g. an invalid/revoked API key, or an unverified sender --
        Brevo reports these as a 4xx with a JSON error body, not a
        network-level failure."""
        response = MagicMock(
            status_code=400,
            text='{"code": "invalid_parameter", "message": "Sender not verified"}',
        )
        fake_client = _make_fake_client(response)

        with patch(
            "backend.services.email_service.httpx.AsyncClient",
            return_value=fake_client,
        ):
            result = await send_password_reset_email(
                settings=_make_settings(),
                to_email="user@example.com",
                reset_url="https://airp.example.com/reset-password?token=abc",
            )

        assert result is False


class TestBuildEmailPayload:
    def test_payload_contains_the_reset_url_and_correct_fields(self) -> None:
        from backend.services.email_service import _build_email_payload

        payload = _build_email_payload(
            to_email="user@example.com",
            from_email="noreply@airp.example.com",
            reset_url="https://airp.example.com/reset-password?token=abc123",
        )
        assert payload["to"] == [{"email": "user@example.com"}]
        assert payload["sender"]["email"] == "noreply@airp.example.com"
        assert payload["subject"]
        assert (
            "https://airp.example.com/reset-password?token=abc123"
            in payload["textContent"]
        )
