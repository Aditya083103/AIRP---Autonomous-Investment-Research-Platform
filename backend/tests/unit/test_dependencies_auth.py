# backend/tests/unit/test_dependencies_auth.py
"""
Unit tests for T-046: backend/dependencies/auth.py

Tests get_current_user() directly (not through a running FastAPI app --
that integration is covered by test_auth_router.py's protected-route
test) with a mocked AsyncSession, mirroring the
_make_mock_session()-style helper already established in
test_state_persistence.py. No real database connection.

Acceptance criterion verified here: "invalid token returns 401" --
every failure path (missing/malformed/expired token, user not found,
deactivated user) must raise HTTPException(401), never a different
status code and never an unguarded exception.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
import uuid

from fastapi import HTTPException
import pytest

from backend.config import Settings
from backend.dependencies.auth import get_current_user
from backend.models.orm import User
from backend.services.auth import create_access_token


def _make_session_returning(user: Any) -> AsyncMock:
    """Return a mocked AsyncSession whose execute().scalar_one_or_none()
    returns ``user`` (a User instance or None)."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=mock_result)
    return session


def _make_active_user(user_id: uuid.UUID | None = None) -> User:
    return User(
        id=user_id if user_id is not None else uuid.uuid4(),
        email="active@example.com",
        password_hash="$2b$12$irrelevant-for-this-test",
        is_active=True,
    )


class TestGetCurrentUserSuccess:
    @pytest.mark.asyncio
    async def test_valid_token_returns_the_matching_user(
        self, test_settings: Settings
    ) -> None:
        user_id = uuid.uuid4()
        user = _make_active_user(user_id)
        token, _ = create_access_token(user_id, settings=test_settings)
        session = _make_session_returning(user)

        result = await get_current_user(
            token=token, session=session, settings=test_settings
        )

        assert result is user


class TestGetCurrentUserFailures:
    @pytest.mark.asyncio
    async def test_garbage_token_raises_401(self, test_settings: Settings) -> None:
        session = _make_session_returning(_make_active_user())

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                token="not-a-real-token", session=session, settings=test_settings
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self, test_settings: Settings) -> None:
        from freezegun import freeze_time

        session = _make_session_returning(_make_active_user())

        with freeze_time("2026-01-01 00:00:00"):
            token, _ = create_access_token(uuid.uuid4(), settings=test_settings)

        with freeze_time("2026-01-01 02:00:00"):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    token=token, session=session, settings=test_settings
                )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_token_for_nonexistent_user_raises_401(
        self, test_settings: Settings
    ) -> None:
        """A structurally valid, correctly signed token whose sub does not
        match any row (e.g. the user was deleted after the token was
        issued) must still be rejected, not raise a different error."""
        token, _ = create_access_token(uuid.uuid4(), settings=test_settings)
        session = _make_session_returning(None)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=token, session=session, settings=test_settings)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_deactivated_user_raises_401(self, test_settings: Settings) -> None:
        user_id = uuid.uuid4()
        inactive_user = User(
            id=user_id,
            email="inactive@example.com",
            password_hash="$2b$12$irrelevant-for-this-test",
            is_active=False,
        )
        token, _ = create_access_token(user_id, settings=test_settings)
        session = _make_session_returning(inactive_user)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=token, session=session, settings=test_settings)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_token_with_non_uuid_sub_raises_401(
        self, test_settings: Settings
    ) -> None:
        """sub must parse as a UUID -- a structurally valid JWT with a
        non-UUID sub (which decode_access_token's Pydantic validation
        does not catch, since TokenPayload.sub is typed as plain str)
        must still be rejected at the UUID-parsing step in
        get_current_user, not raise an unguarded ValueError."""
        from jose import jwt as raw_jwt

        token_with_bad_sub = raw_jwt.encode(
            {"sub": "not-a-valid-uuid", "exp": 9999999999},
            test_settings.secret_key,
            algorithm="HS256",
        )
        session = _make_session_returning(_make_active_user())

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                token=token_with_bad_sub, session=session, settings=test_settings
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_401_includes_www_authenticate_header(
        self, test_settings: Settings
    ) -> None:
        """Standard OAuth2/bearer convention -- a 401 should advertise the
        expected auth scheme so well-behaved clients can react correctly."""
        session = _make_session_returning(_make_active_user())

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                token="garbage", session=session, settings=test_settings
            )
        assert exc_info.value.headers is not None
        assert exc_info.value.headers.get("WWW-Authenticate") == "Bearer"
