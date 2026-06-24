# backend/dependencies/auth.py
"""
AIRP -- Auth Dependency (T-046)

get_current_user() is the FastAPI dependency every protected route adds
to its signature. Extracts the bearer token from the Authorization
header (via OAuth2PasswordBearer, which also wires up the "Authorize"
button in Swagger UI at /docs), verifies it via
backend.services.auth.decode_access_token, loads the corresponding
User row from PostgreSQL, and returns it -- or raises HTTPException(401)
for every failure mode (missing header, malformed token, expired token,
wrong signature, user deleted after the token was issued, or a
deactivated account).

Acceptance criterion this module exists to satisfy: "invalid token
returns 401".
"""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.db.session import get_async_session
from backend.dependencies.common import get_settings_dependency
from backend.models.orm import User
from backend.services.auth import InvalidTokenError, decode_access_token

__all__ = ["get_current_user", "oauth2_scheme"]

#: tokenUrl points Swagger UI's "Authorize" dialog at the login endpoint
#: so /docs can obtain a real token interactively. FastAPI does not call
#: this URL itself outside of that UI flow -- get_current_user always
#: does its own verification via decode_access_token below.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

#: Single shared exception instance for "invalid credentials" -- every
#: failure path below raises this exact response, by design (see
#: InvalidTokenError's docstring in services/auth.py for why expired,
#: malformed, and wrong-signature tokens are not distinguished).
_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings_dependency),
) -> User:
    """
    Resolve the bearer token to a User row, or raise HTTPException(401).

    Usage (any protected route):
        from fastapi import Depends
        from backend.dependencies.auth import get_current_user
        from backend.models.orm import User

        @router.get("/protected")
        async def protected_route(
            current_user: User = Depends(get_current_user),
        ) -> dict[str, str]:
            return {"email": current_user.email}
    """
    try:
        payload = decode_access_token(token, settings=settings)
    except InvalidTokenError:
        raise _UNAUTHORIZED from None

    try:
        user_id = uuid.UUID(payload.sub)
    except (AttributeError, ValueError):
        # AttributeError: payload.sub is missing/not a string (shouldn't
        # happen -- TokenPayload requires sub: str -- but defends against
        # a future schema change). ValueError: sub is a string that is
        # not a valid UUID, e.g. a token forged or corrupted after
        # signing in a way that still passes signature verification
        # (impossible in practice with HS256, but this guards the
        # invariant explicitly rather than trusting the database driver
        # to reject a malformed value safely).
        raise _UNAUTHORIZED from None

    result = await session.execute(select(User).where(User.id == user_id))

    user = result.scalar_one_or_none()
    if user is None:
        raise _UNAUTHORIZED

    if not user.is_active:
        raise _UNAUTHORIZED

    return user
