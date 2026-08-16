# backend/services/preference_service.py
"""
AIRP -- User Preferences Service (T-099 schema, extended T-106)

Pure service-layer code with no FastAPI imports -- mirrors
``backend/services/chat_session_service.py``'s own stated reasoning for
the same convention, so this stays independently testable without
spinning up an ASGI app.

Two responsibilities:
    get_or_create_user_preferences  -- lazy row creation, exactly as
                                        T-099's own ``UserPreferences``
                                        docstring already documents
                                        ("created lazily on first
                                        access rather than at
                                        registration time") but which
                                        no module actually implemented
                                        until this task.
    apply_extracted_preferences     -- T-106's "ask and remember...
                                        once" write path: persists a
                                        ``PreferenceExtractionResult``
                                        (backend/services/
                                        preference_extractor.py) onto a
                                        user's row, but ONLY for a
                                        field that is not already known.

Why "only write when still unknown", not "always overwrite with the
latest mention"
------------------------------------------------------------------------
T-106's task description is explicit: "ask and remember... ONCE".
Chat is a conversational surface, not a settings form -- a user might
mention "high risk" in passing while asking an unrelated question
about a company they consider risky, without meaning to redeclare
their own risk appetite. Overwriting a previously-confirmed preference
on every loosely-matching mention would make the assistant's tone
silently drift based on conversational noise rather than a genuine,
deliberate answer to the one question it is allowed to ask. Once a
field is set, changing it is left to a future, explicit settings
surface (not part of this task's acceptance criteria) -- this module
enforces that boundary at the persistence layer so no caller can
accidentally violate it by calling this function on every turn (which
``backend/routers/chat_stream.py`` does, by design -- see that
module's own docstring).

Why this never touches ``theme`` / ``chat_response_style`` /
``default_exchange`` / ``watchlist_tickers`` / ``email_notifications_enabled``
------------------------------------------------------------------------
Those five columns are read-only from this module's point of view --
``apply_extracted_preferences`` only ever sets ``risk_appetite`` and/or
``preferred_sectors``, the two columns T-106's migration added. Every
other column keeps whatever value it already had (its own default on a
freshly created row, from ``get_or_create_user_preferences``).

Design decisions
------------------------------------------------------------------------
* NO ``from __future__ import annotations`` -- matches
  ``chat_session_service.py`` and every other Phase 10 chat-feature
  service module.
* Plain ASCII section comments (# ---).
* No bare ``type: ignore``.
* Never raises on the "row already exists" race -- see
  ``get_or_create_user_preferences``'s own docstring for the
  IntegrityError-and-refetch fallback.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.orm import UserPreferences
from backend.services.preference_extractor import PreferenceExtractionResult

logger = logging.getLogger(__name__)

__all__ = [
    "get_or_create_user_preferences",
    "apply_extracted_preferences",
]


# ---------------------------------------------------------------------------
# Lazy row creation
# ---------------------------------------------------------------------------


async def get_or_create_user_preferences(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> UserPreferences:
    """
    Return ``user_id``'s ``UserPreferences`` row, creating it (with
    every column's schema default -- see T-099's migration) if it does
    not exist yet.

    Handles the "two concurrent first requests for the same brand-new
    user both try to insert" race: ``user_preferences.user_id`` has a
    UNIQUE constraint (``uq_user_preferences_user_id``, T-099), so the
    loser of that race gets an ``IntegrityError`` on commit rather than
    a duplicate row -- caught here, rolled back, and re-read rather
    than propagated, since the row this caller wanted now exists either
    way (just not the one this particular call created).

    Args:
        session: Active AsyncSession for this request.
        user_id: UUID of the user.

    Returns:
        The user's UserPreferences row (existing or newly created).
    """
    existing = await session.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    prefs = existing.scalar_one_or_none()
    if prefs is not None:
        return prefs

    prefs = UserPreferences(user_id=user_id)
    session.add(prefs)
    try:
        await session.commit()
    except IntegrityError:
        logger.debug(
            "get_or_create_user_preferences: lost creation race for "
            "user_id=%s -- re-reading the row the other request created",
            user_id,
        )
        await session.rollback()
        refetched = await session.execute(
            select(UserPreferences).where(UserPreferences.user_id == user_id)
        )
        return refetched.scalar_one()

    await session.refresh(prefs)
    return prefs


# ---------------------------------------------------------------------------
# Personalization write-once path (T-106)
# ---------------------------------------------------------------------------


async def apply_extracted_preferences(
    session: AsyncSession,
    user_id: uuid.UUID,
    extraction: PreferenceExtractionResult,
) -> UserPreferences:
    """
    Persist a preference-extraction result onto the user's row, WITHOUT
    overwriting a field that is already known.

    Safe to call on every chat turn (as ``backend/routers/
    chat_stream.py`` does): once ``risk_appetite`` and
    ``preferred_sectors`` are both already set, this becomes a
    read-only no-op forever for that user -- no write, no commit --
    which is exactly the "ask... once" contract this task's acceptance
    criteria describe.

    Args:
        session:    Active AsyncSession for this request.
        user_id:    UUID of the user.
        extraction: Output of
            ``backend.services.preference_extractor.extract_preferences``
            for the message just received.

    Returns:
        The user's UserPreferences row, reflecting any change just
        made (or unchanged, if nothing new was recognised or
        everything recognised was already known).
    """
    prefs = await get_or_create_user_preferences(session, user_id)

    changed = False

    if extraction.risk_appetite is not None and prefs.risk_appetite is None:
        prefs.risk_appetite = extraction.risk_appetite
        changed = True

    if extraction.preferred_sectors and not prefs.preferred_sectors:
        prefs.preferred_sectors = extraction.preferred_sectors
        changed = True

    if not changed:
        return prefs

    session.add(prefs)
    await session.commit()
    await session.refresh(prefs)

    logger.debug(
        "apply_extracted_preferences: user_id=%s risk_appetite=%r "
        "preferred_sectors=%r",
        user_id,
        prefs.risk_appetite,
        prefs.preferred_sectors,
    )
    return prefs
