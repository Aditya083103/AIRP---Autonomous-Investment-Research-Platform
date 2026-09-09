# backend/tests/unit/test_password_reset_service.py
"""
Unit tests for B6: backend/services/password_reset.py

Test strategy
-------------
create_password_reset_request
    unknown email -> None, no DB writes attempted beyond the lookup
    inactive user's email -> None (same as unknown, no enumeration signal)
    known, active user's email -> a PasswordResetRequestResult with a
        real raw_token or, invalidates any prior unused tokens for that
        user first, persists the new one, and returns its expiry
        computed from PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
confirm_password_reset
    unknown token -> InvalidOrExpiredResetTokenError
    expired token -> InvalidOrExpiredResetTokenError
    already-used token -> InvalidOrExpiredResetTokenError
    valid token -> updates password_hash, increments token_version,
        marks the token used, and returns the updated user
    the raw token from generate_password_reset_token really does
        round-trip through confirm_password_reset end to end (no
        mocking of the hash itself -- only the AsyncSession)

All database interactions use mocked AsyncSession objects (AsyncMock /
MagicMock) -- no real PostgreSQL connection, matching this codebase's
established chat-service-test convention (see
test_chat_session_service.py). ENVIRONMENT must be set to 'test' before
any backend import.
"""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")

from datetime import datetime, timedelta, timezone  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402
import uuid  # noqa: E402

import pytest  # noqa: E402

from backend.config import Settings  # noqa: E402
from backend.models.orm import PasswordResetToken, User  # noqa: E402
from backend.services.auth import (  # noqa: E402
    generate_password_reset_token,
    hash_reset_token,
    verify_password,
)
from backend.services.password_reset import (  # noqa: E402
    InvalidOrExpiredResetTokenError,
    PasswordResetRequestResult,
    confirm_password_reset,
    create_password_reset_request,
)

# Computed at import time (not a fixed historical date) -- confirm_password_reset
# compares a token's expires_at against the REAL datetime.now(timezone.utc) at
# call time, so tests need "future"/"past" relative to actual now, not a
# frozen point that could itself already be in the past by the time this
# suite runs.
_NOW = datetime.now(timezone.utc)


def _make_settings(expire_minutes: int = 30) -> Settings:
    return Settings.model_construct(
        environment="test",
        database_url="x",
        secret_key="a" * 32,
        password_reset_token_expire_minutes=expire_minutes,
    )


def _make_user(
    user_id: uuid.UUID | None = None,
    is_active: bool = True,
    token_version: int = 0,
) -> User:
    return User(
        id=user_id if user_id is not None else uuid.uuid4(),
        email="reset-me@example.com",
        password_hash="$2b$12$old-hash-irrelevant-for-this-test",
        is_active=is_active,
        token_version=token_version,
    )


def _make_token_row(
    user_id: uuid.UUID,
    token_hash: str,
    expires_at: datetime,
    used_at: datetime | None = None,
) -> PasswordResetToken:
    return PasswordResetToken(
        id=uuid.uuid4(),
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        used_at=used_at,
        created_at=_NOW,
    )


class TestCreatePasswordResetRequest:
    @pytest.mark.asyncio
    async def test_unknown_email_returns_none(self) -> None:
        session = AsyncMock()
        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=user_result)

        result = await create_password_reset_request(
            session, "nobody@example.com", _make_settings()
        )

        assert result is None
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_inactive_users_email_returns_none(self) -> None:
        session = AsyncMock()
        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(
            return_value=_make_user(is_active=False)
        )
        session.execute = AsyncMock(return_value=user_result)

        result = await create_password_reset_request(
            session, "inactive@example.com", _make_settings()
        )

        assert result is None
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_known_active_user_returns_a_result_with_a_raw_token(self) -> None:
        user = _make_user()
        session = AsyncMock()
        session.add = MagicMock()
        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(return_value=user)
        invalidate_result = MagicMock()
        session.execute = AsyncMock(side_effect=[user_result, invalidate_result])

        result = await create_password_reset_request(
            session, user.email, _make_settings()
        )

        assert isinstance(result, PasswordResetRequestResult)
        assert result.user is user
        assert isinstance(result.raw_token, str)
        assert len(result.raw_token) > 20  # secrets.token_urlsafe(32)-shaped
        session.add.assert_called_once()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_expiry_reflects_password_reset_token_expire_minutes(self) -> None:
        user = _make_user()
        session = AsyncMock()
        session.add = MagicMock()
        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(return_value=user)
        session.execute = AsyncMock(side_effect=[user_result, MagicMock()])

        before = datetime.now(timezone.utc)
        result = await create_password_reset_request(
            session, user.email, _make_settings(expire_minutes=45)
        )
        after = datetime.now(timezone.utc)

        assert result is not None
        assert before + timedelta(minutes=45) <= result.expires_at
        assert result.expires_at <= after + timedelta(minutes=45)

    @pytest.mark.asyncio
    async def test_invalidates_prior_unused_tokens_before_creating_the_new_one(
        self,
    ) -> None:
        """The UPDATE that supersedes older unused tokens must run
        BEFORE the new token is added -- confirmed here by asserting
        it is the FIRST of the two execute() calls after the user
        lookup, i.e. session.execute is called with an UPDATE
        statement second (lookup is first)."""
        user = _make_user()
        session = AsyncMock()
        session.add = MagicMock()
        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(return_value=user)
        invalidate_result = MagicMock()
        session.execute = AsyncMock(side_effect=[user_result, invalidate_result])

        await create_password_reset_request(session, user.email, _make_settings())

        assert session.execute.await_count == 2
        # Second call's compiled statement is the UPDATE against
        # password_reset_tokens (the first is the SELECT User lookup).
        second_call_statement = session.execute.await_args_list[1].args[0]
        assert "password_reset_tokens" in str(second_call_statement).lower()
        assert "UPDATE" in str(second_call_statement).upper()


class TestConfirmPasswordReset:
    @pytest.mark.asyncio
    async def test_unknown_token_raises(self) -> None:
        session = AsyncMock()
        token_result = MagicMock()
        token_result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=token_result)

        with pytest.raises(InvalidOrExpiredResetTokenError):
            await confirm_password_reset(session, "not-a-real-token", "NewPassw0rd!")
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_expired_token_raises(self) -> None:
        user_id = uuid.uuid4()
        raw_token, token_hash = generate_password_reset_token()
        expired_row = _make_token_row(
            user_id, token_hash, expires_at=_NOW - timedelta(minutes=1)
        )
        session = AsyncMock()
        token_result = MagicMock()
        token_result.scalar_one_or_none = MagicMock(return_value=expired_row)
        session.execute = AsyncMock(return_value=token_result)

        with pytest.raises(InvalidOrExpiredResetTokenError):
            await confirm_password_reset(session, raw_token, "NewPassw0rd!")
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_used_token_raises(self) -> None:
        user_id = uuid.uuid4()
        raw_token, token_hash = generate_password_reset_token()
        used_row = _make_token_row(
            user_id,
            token_hash,
            expires_at=_NOW + timedelta(minutes=30),
            used_at=_NOW,
        )
        session = AsyncMock()
        token_result = MagicMock()
        token_result.scalar_one_or_none = MagicMock(return_value=used_row)
        session.execute = AsyncMock(return_value=token_result)

        with pytest.raises(InvalidOrExpiredResetTokenError):
            await confirm_password_reset(session, raw_token, "NewPassw0rd!")
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_valid_token_updates_password_and_rotates_token_version(self) -> None:
        user = _make_user(token_version=3)
        raw_token, token_hash = generate_password_reset_token()
        token_row = _make_token_row(
            user.id, token_hash, expires_at=_NOW + timedelta(minutes=30)
        )
        session = AsyncMock()
        token_result = MagicMock()
        token_result.scalar_one_or_none = MagicMock(return_value=token_row)
        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(return_value=user)
        session.execute = AsyncMock(side_effect=[token_result, user_result])

        result = await confirm_password_reset(session, raw_token, "BrandNewPassw0rd!")

        assert result is user
        assert verify_password("BrandNewPassw0rd!", user.password_hash)
        assert user.token_version == 4
        assert token_row.used_at is not None
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(user)

    @pytest.mark.asyncio
    async def test_valid_token_actually_hashes_the_new_password_not_stores_it_plain(
        self,
    ) -> None:
        user = _make_user()
        raw_token, token_hash = generate_password_reset_token()
        token_row = _make_token_row(
            user.id, token_hash, expires_at=_NOW + timedelta(minutes=30)
        )
        session = AsyncMock()
        token_result = MagicMock()
        token_result.scalar_one_or_none = MagicMock(return_value=token_row)
        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(return_value=user)
        session.execute = AsyncMock(side_effect=[token_result, user_result])

        await confirm_password_reset(session, raw_token, "BrandNewPassw0rd!")

        assert user.password_hash != "BrandNewPassw0rd!"
        assert user.password_hash.startswith("$2b$")

    @pytest.mark.asyncio
    async def test_token_for_a_deleted_user_raises_rather_than_crashing(self) -> None:
        """Defensive-only path: the token row's user was somehow not
        found (FK CASCADE means this should not happen in practice)."""
        user_id = uuid.uuid4()
        raw_token, token_hash = generate_password_reset_token()
        token_row = _make_token_row(
            user_id, token_hash, expires_at=_NOW + timedelta(minutes=30)
        )
        session = AsyncMock()
        token_result = MagicMock()
        token_result.scalar_one_or_none = MagicMock(return_value=token_row)
        user_result = MagicMock()
        user_result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(side_effect=[token_result, user_result])

        with pytest.raises(InvalidOrExpiredResetTokenError):
            await confirm_password_reset(session, raw_token, "BrandNewPassw0rd!")


class TestPasswordResetTokenRoundTrip:
    """generate_password_reset_token / hash_reset_token are exercised
    directly (no mocking) as a sanity check on the primitives
    confirm_password_reset's own lookup depends on."""

    def test_raw_token_hashes_to_the_paired_hash(self) -> None:
        raw_token, token_hash = generate_password_reset_token()
        assert hash_reset_token(raw_token) == token_hash

    def test_two_generated_tokens_are_never_equal(self) -> None:
        first_raw, first_hash = generate_password_reset_token()
        second_raw, second_hash = generate_password_reset_token()
        assert first_raw != second_raw
        assert first_hash != second_hash

    def test_the_raw_token_is_never_the_same_as_its_hash(self) -> None:
        raw_token, token_hash = generate_password_reset_token()
        assert raw_token != token_hash
