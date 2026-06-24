# backend/routers/auth.py
"""
AIRP -- Auth Router (T-046)

POST /auth/register, POST /auth/login, GET /auth/me.

Acceptance criteria (from task spec):
  * Register -> login -> access protected route works end-to-end
  * Invalid token returns 401

Business logic (password hashing, JWT encode/decode) lives in
backend.services.auth; this module only handles the HTTP-layer
concerns -- request validation (via Pydantic schemas), database
queries, and translating service-layer exceptions into HTTP responses.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.db.session import get_async_session
from backend.dependencies.auth import get_current_user
from backend.dependencies.common import get_settings_dependency
from backend.models.orm import User
from backend.models.schemas import (
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from backend.services.auth import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description=(
        "Creates a new user with a bcrypt-hashed password and returns an "
        "access token, identical in shape to POST /auth/login -- a newly "
        "registered user is immediately authenticated, no separate login "
        "step required."
    ),
)
async def register(
    body: UserRegisterRequest,
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings_dependency),
) -> TokenResponse:
    existing = await session.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # Defense-in-depth: two concurrent registrations for the same
        # email racing past the SELECT above both reach INSERT, and the
        # unique constraint on users.email rejects the second one at
        # the database level. Roll back so this session is usable again
        # if the caller (or a test) inspects it afterward.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        ) from None
    await session.refresh(user)

    access_token, expires_in = create_access_token(user.id, settings=settings)
    return TokenResponse(
        access_token=access_token,
        expires_in_minutes=expires_in,
        user=UserResponse.model_validate(user),
    )


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in with email and password",
    description="Returns an access token on success; 401 on bad credentials.",
)
async def login(
    body: UserLoginRequest,
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings_dependency),
) -> TokenResponse:
    result = await session.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    # Deliberately the same error for "no such user" and "wrong password"
    # -- distinguishing them lets an attacker enumerate registered
    # emails, which has no legitimate use to a real caller.
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
    )

    if user is None:
        raise invalid_credentials
    if not verify_password(body.password, user.password_hash):
        raise invalid_credentials
    if not user.is_active:
        raise invalid_credentials

    access_token, expires_in = create_access_token(user.id, settings=settings)
    return TokenResponse(
        access_token=access_token,
        expires_in_minutes=expires_in,
        user=UserResponse.model_validate(user),
    )


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Return the currently authenticated user",
    description=(
        "Requires a valid bearer token (Authorization: Bearer <token>). "
        "Returns 401 for any missing, malformed, expired, or otherwise "
        "invalid token -- the canonical protected-route example other "
        "routers should follow."
    ),
)
async def read_current_user(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    return UserResponse.model_validate(current_user)
