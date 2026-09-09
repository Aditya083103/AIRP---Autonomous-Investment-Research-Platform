# backend/services/password_reset.py
"""
AIRP -- Password reset service (B6)

Business logic behind POST /auth/password-reset/request and
POST /auth/password-reset/confirm (backend/routers/auth.py). Pure
service-layer code with no FastAPI imports, mirroring
backend.services.auth's own "HTTP concerns live in the router, this
module stays independently testable" split.

Why ``create_password_reset_request`` returns None instead of raising
for "no such user"
------------------------------------------------------------------------
Mirrors backend.services.auth's InvalidCredentialsError-avoids-
enumeration philosophy, one level up: the ROUTER must return the exact
same 200 response whether or not ``email`` matched a real, active
account (see backend/routers/auth.py's own docstring), so this
function hands back ``None`` for "nothing to do" rather than an
exception the router would have to catch-and-ignore -- a None return
is the more honest signature for "this is not an error condition the
caller needs to react to differently."

Why a fresh request invalidates every OTHER unused token for the same
user
------------------------------------------------------------------------
Without this, an intercepted-but-not-yet-used reset email from an hour
ago and a freshly-requested one would BOTH remain valid simultaneously
-- reusing ``used_at`` (rather than adding a separate
"superseded"/"revoked" column) to mark a superseded token as no longer
usable is a deliberate simplification: functionally, a superseded
token and a consumed one are identical from confirm_password_reset's
point of view (neither can ever succeed again), and B6 has no product
need to distinguish "why" a token stopped being usable.

Public API
----------
    from backend.services.password_reset import (
        InvalidOrExpiredResetTokenError,
        PasswordResetRequestResult,
        create_password_reset_request,
        confirm_password_reset,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.models.orm import PasswordResetToken, User
from backend.services.auth import (
    generate_password_reset_token,
    hash_password,
    hash_reset_token,
)

logger = logging.getLogger(__name__)

__all__ = [
    "InvalidOrExpiredResetTokenError",
    "PasswordResetRequestResult",
    "create_password_reset_request",
    "confirm_password_reset",
]


class InvalidOrExpiredResetTokenError(Exception):
    """
    Raised by confirm_password_reset for any unusable token: not
    found, expired, or already used/superseded.

    Deliberately one exception type for all three -- the same
    "distinguishing failure modes only helps an attacker, never a
    legitimate caller" reasoning backend.services.auth.InvalidTokenError's
    own docstring gives: a caller with a genuinely expired link and an
    attacker guessing at tokens both just need "this didn't work,
    request a new one", not a hint about which specific way it failed.
    """


@dataclass(frozen=True)
class PasswordResetRequestResult:
    """What create_password_reset_request hands back when ``email``
    matched a real, active user."""

    user: User
    raw_token: str
    expires_at: datetime


async def create_password_reset_request(
    session: AsyncSession, email: str, settings: Settings
) -> Optional[PasswordResetRequestResult]:
    """
    Look up ``email``; if it matches a real, active user, invalidate
    that user's other still-usable tokens, create a new one, and
    return it (raw token included -- the ONLY point in this token's
    lifetime the raw value is ever available; the caller must send it
    now, since only its hash is persisted).

    Args:
        session:  Active AsyncSession for this request.
        email:    Whatever the caller typed as the account email.
        settings: Used for PASSWORD_RESET_TOKEN_EXPIRE_MINUTES.

    Returns:
        A PasswordResetRequestResult when ``email`` matched a real,
        active user, or None otherwise -- see this module's own
        docstring for why None (not an exception).
    """
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None

    now = datetime.now(timezone.utc)

    await session.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )

    raw_token, token_hash = generate_password_reset_token()
    expires_at = now + timedelta(minutes=settings.password_reset_token_expire_minutes)
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    await session.commit()

    logger.info("password_reset: issued a reset token for user_id=%s", user.id)
    return PasswordResetRequestResult(
        user=user, raw_token=raw_token, expires_at=expires_at
    )


async def confirm_password_reset(
    session: AsyncSession, raw_token: str, new_password: str
) -> User:
    """
    Verify ``raw_token``, update the matching user's password, rotate
    their sessions, and mark the token consumed.

    "Rotate sessions" (B6's own wording) means incrementing
    ``users.token_version`` -- every access token issued before this
    call carries the OLD version and is rejected by
    backend.dependencies.auth.get_current_user on its very next use,
    regardless of its own expiry. See that dependency's own comment
    for the mechanism.

    Args:
        session:      Active AsyncSession for this request.
        raw_token:    The raw token value the caller supplied (from the
                      emailed link) -- hashed here and matched against
                      ``password_reset_tokens.token_hash``.
        new_password: The new plaintext password to hash and persist.

    Returns:
        The updated User.

    Raises:
        InvalidOrExpiredResetTokenError: ``raw_token`` does not match
            any row, or the matching row is expired or already
            used/superseded.
    """
    token_hash = hash_reset_token(raw_token)
    result = await session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    token_row = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if token_row is None or token_row.used_at is not None or token_row.expires_at < now:
        raise InvalidOrExpiredResetTokenError(
            "reset token is invalid, expired, or already used"
        )

    user_result = await session.execute(
        select(User).where(User.id == token_row.user_id)
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        # Defensive only: password_reset_tokens.user_id FK CASCADEs on
        # user deletion, so a token row referencing a nonexistent user
        # should not exist in practice -- guarded explicitly rather
        # than trusting that invariant to hold forever.
        raise InvalidOrExpiredResetTokenError(
            "reset token is invalid, expired, or already used"
        )

    user.password_hash = hash_password(new_password)
    user.token_version += 1
    token_row.used_at = now
    await session.commit()
    await session.refresh(user)

    logger.info("password_reset: password reset completed for user_id=%s", user.id)
    return user
