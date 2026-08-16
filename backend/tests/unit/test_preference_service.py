# backend/tests/unit/test_preference_service.py
"""
Unit tests for T-106: backend/services/preference_service.py

Test strategy
-------------
1. get_or_create_user_preferences
     existing row found            -- returned as-is, no add/commit
     no row exists                 -- a new UserPreferences is
       constructed, added, committed, and refreshed
     commit raises IntegrityError  -- rolled back and the row is
       re-read rather than the error propagating (the "lost the
       creation race" fallback)
2. apply_extracted_preferences
     nothing extracted             -- no-op, no commit
     risk_appetite newly learned, currently unset -- written, commit
       called
     risk_appetite already known   -- NOT overwritten by a new
       extraction, no commit
     preferred_sectors newly learned, currently empty -- written
     preferred_sectors already known -- NOT overwritten, no commit
     both already known            -- fully no-op even though
       extraction found both again

All database interactions use mocked AsyncSession objects (AsyncMock /
MagicMock) -- no real PostgreSQL connection, mirroring
test_chat_service.py's established pattern for this codebase's Phase
10 chat-feature service tests. ENVIRONMENT must be set to 'test' before
any backend import.
"""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")

from typing import Optional  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402
import uuid  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from backend.models.orm import UserPreferences  # noqa: E402
from backend.services.preference_extractor import (  # noqa: E402
    PreferenceExtractionResult,
)
from backend.services.preference_service import (  # noqa: E402
    apply_extracted_preferences,
    get_or_create_user_preferences,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _fake_refresh(instance: UserPreferences) -> None:
    """
    Simulate what a real ``session.refresh()`` round trip to PostgreSQL
    would populate via T-099's column ``server_default``s -- a freshly
    constructed (never-flushed) ORM instance has these as None (Python
    never applied them; only a real INSERT would), so this mimics that
    without a real database.
    """
    if instance.preferred_sectors is None:
        instance.preferred_sectors = []
    if instance.chat_response_style is None:
        instance.chat_response_style = "concise"
    if instance.theme is None:
        instance.theme = "system"
    if instance.email_notifications_enabled is None:
        instance.email_notifications_enabled = True


def _make_session(existing: Optional[UserPreferences] = None) -> AsyncMock:
    """An AsyncSession mock returning ``existing`` from the first select."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=existing)
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock(side_effect=_fake_refresh)
    session.rollback = AsyncMock()
    return session


def _make_prefs(
    user_id: uuid.UUID,
    risk_appetite: Optional[str] = None,
    preferred_sectors: Optional[list] = None,  # type: ignore[type-arg]
) -> UserPreferences:
    prefs = UserPreferences(user_id=user_id)
    prefs.risk_appetite = risk_appetite
    prefs.preferred_sectors = preferred_sectors if preferred_sectors is not None else []
    prefs.chat_response_style = "concise"
    return prefs


# ---------------------------------------------------------------------------
# get_or_create_user_preferences
# ---------------------------------------------------------------------------


class TestGetOrCreateUserPreferences:
    @pytest.mark.asyncio
    async def test_returns_existing_row_without_writing(self) -> None:
        user_id = uuid.uuid4()
        existing = _make_prefs(user_id, risk_appetite="moderate")
        session = _make_session(existing=existing)

        result = await get_or_create_user_preferences(session, user_id)

        assert result is existing
        session.add.assert_not_called()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_creates_a_new_row_when_none_exists(self) -> None:
        user_id = uuid.uuid4()
        session = _make_session(existing=None)

        result = await get_or_create_user_preferences(session, user_id)

        assert result.user_id == user_id
        session.add.assert_called_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_new_row_has_no_personalization_preferences_yet(self) -> None:
        user_id = uuid.uuid4()
        session = _make_session(existing=None)

        result = await get_or_create_user_preferences(session, user_id)

        assert result.risk_appetite is None
        assert result.preferred_sectors == []

    @pytest.mark.asyncio
    async def test_creation_race_falls_back_to_re_reading_the_row(self) -> None:
        user_id = uuid.uuid4()
        winner_row = _make_prefs(user_id, risk_appetite="aggressive")

        session = AsyncMock()
        first_result = MagicMock()
        first_result.scalar_one_or_none = MagicMock(return_value=None)
        second_result = MagicMock()
        second_result.scalar_one = MagicMock(return_value=winner_row)
        session.execute = AsyncMock(side_effect=[first_result, second_result])
        session.add = MagicMock()
        session.commit = AsyncMock(
            side_effect=IntegrityError(
                statement="INSERT", params={}, orig=Exception("dup")
            )
        )
        session.rollback = AsyncMock()
        session.refresh = AsyncMock(side_effect=_fake_refresh)

        result = await get_or_create_user_preferences(session, user_id)

        assert result is winner_row
        session.rollback.assert_awaited_once()
        assert session.execute.await_count == 2


# ---------------------------------------------------------------------------
# apply_extracted_preferences -- write-once contract
# ---------------------------------------------------------------------------


class TestApplyExtractedPreferencesNoOp:
    @pytest.mark.asyncio
    async def test_nothing_extracted_is_a_pure_no_op(self) -> None:
        user_id = uuid.uuid4()
        existing = _make_prefs(user_id)
        session = _make_session(existing=existing)

        result = await apply_extracted_preferences(
            session, user_id, PreferenceExtractionResult()
        )

        assert result is existing
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_both_already_known_ignores_a_repeated_extraction(self) -> None:
        user_id = uuid.uuid4()
        existing = _make_prefs(
            user_id, risk_appetite="conservative", preferred_sectors=["IT"]
        )
        session = _make_session(existing=existing)

        extraction = PreferenceExtractionResult(
            risk_appetite="aggressive", preferred_sectors=["FMCG"]
        )
        result = await apply_extracted_preferences(session, user_id, extraction)

        # Neither field is overwritten -- the ORIGINAL values remain.
        assert result.risk_appetite == "conservative"
        assert result.preferred_sectors == ["IT"]
        session.commit.assert_not_awaited()


class TestApplyExtractedPreferencesWritesOnceEach:
    @pytest.mark.asyncio
    async def test_risk_appetite_written_when_previously_unset(self) -> None:
        user_id = uuid.uuid4()
        existing = _make_prefs(user_id, risk_appetite=None)
        session = _make_session(existing=existing)

        extraction = PreferenceExtractionResult(risk_appetite="moderate")
        result = await apply_extracted_preferences(session, user_id, extraction)

        assert result.risk_appetite == "moderate"
        session.add.assert_called_once_with(existing)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_risk_appetite_not_overwritten_when_already_set(self) -> None:
        user_id = uuid.uuid4()
        existing = _make_prefs(user_id, risk_appetite="conservative")
        session = _make_session(existing=existing)

        extraction = PreferenceExtractionResult(risk_appetite="aggressive")
        result = await apply_extracted_preferences(session, user_id, extraction)

        assert result.risk_appetite == "conservative"
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_preferred_sectors_written_when_previously_empty(self) -> None:
        user_id = uuid.uuid4()
        existing = _make_prefs(user_id, preferred_sectors=[])
        session = _make_session(existing=existing)

        extraction = PreferenceExtractionResult(preferred_sectors=["IT", "FMCG"])
        result = await apply_extracted_preferences(session, user_id, extraction)

        assert result.preferred_sectors == ["IT", "FMCG"]
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_preferred_sectors_not_overwritten_when_already_set(self) -> None:
        user_id = uuid.uuid4()
        existing = _make_prefs(user_id, preferred_sectors=["Auto"])
        session = _make_session(existing=existing)

        extraction = PreferenceExtractionResult(preferred_sectors=["FMCG"])
        result = await apply_extracted_preferences(session, user_id, extraction)

        assert result.preferred_sectors == ["Auto"]
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_both_fields_can_be_written_in_one_call(self) -> None:
        user_id = uuid.uuid4()
        existing = _make_prefs(user_id, risk_appetite=None, preferred_sectors=[])
        session = _make_session(existing=existing)

        extraction = PreferenceExtractionResult(
            risk_appetite="aggressive", preferred_sectors=["Auto", "IT"]
        )
        result = await apply_extracted_preferences(session, user_id, extraction)

        assert result.risk_appetite == "aggressive"
        assert result.preferred_sectors == ["Auto", "IT"]
        # One commit for the single combined write, not two.
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_the_row_first_if_it_does_not_exist_yet(self) -> None:
        user_id = uuid.uuid4()
        session = _make_session(existing=None)

        extraction = PreferenceExtractionResult(risk_appetite="moderate")
        result = await apply_extracted_preferences(session, user_id, extraction)

        assert result.user_id == user_id
        assert result.risk_appetite == "moderate"
        # One commit for the lazy row creation, one for the write --
        # get_or_create_user_preferences and apply_extracted_preferences
        # each commit their own unit of work.
        assert session.commit.await_count == 2
