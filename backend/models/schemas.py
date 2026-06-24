# backend/models/schemas.py
"""
AIRP -- Pydantic Request/Response Schemas (T-046)

Pydantic v2 models for the auth endpoints' request bodies and response
shapes. Kept in a separate module from backend/models/orm.py because
these are API contract schemas (validated at the HTTP boundary), not
database table definitions -- the two evolve independently and mixing
them invites accidentally serialising a database-only field (like
password_hash) straight into an API response.

PRIORITY INSTRUCTION (project-wide rule): no `from __future__ import
annotations` in this module -- it breaks Pydantic v2 union resolution
at class-definition time.
"""

from datetime import datetime
from typing import Optional
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

__all__ = [
    "UserRegisterRequest",
    "UserLoginRequest",
    "UserResponse",
    "TokenResponse",
    "TokenPayload",
]

# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------

#: Minimum password length enforced at the API boundary. bcrypt itself
#: silently ignores bytes beyond 72, so the upper bound below keeps the
#: full password meaningfully hashed rather than truncated.
_MIN_PASSWORD_LENGTH = 8
_MAX_PASSWORD_LENGTH = 72


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class UserRegisterRequest(BaseModel):
    """Body for POST /auth/register."""

    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(
        ...,
        min_length=_MIN_PASSWORD_LENGTH,
        max_length=_MAX_PASSWORD_LENGTH,
        description=f"Plaintext password, {_MIN_PASSWORD_LENGTH}-"
        f"{_MAX_PASSWORD_LENGTH} characters. Never stored or logged as-is.",
    )
    display_name: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional display name shown in the dashboard",
    )

    @field_validator("password")
    @classmethod
    def _reject_whitespace_only(cls, value: str) -> str:
        """Reject a password that is technically long enough but blank."""
        if not value.strip():
            raise ValueError("password must not be empty or whitespace-only")
        return value


class UserLoginRequest(BaseModel):
    """Body for POST /auth/login."""

    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., description="Plaintext password")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class UserResponse(BaseModel):
    """
    Public-safe user representation returned by /auth/register,
    /auth/login (nested under TokenResponse), and GET /auth/me.

    Deliberately excludes password_hash -- model_config's from_attributes
    lets this be built directly from a backend.models.orm.User ORM
    instance via UserResponse.model_validate(user), and since this
    schema has no password_hash field, there is no risk of it leaking
    into a response even if a future edit naively passed the whole ORM
    object through.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: Optional[str] = None
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """Body returned by both POST /auth/register and POST /auth/login."""

    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    user: UserResponse


class TokenPayload(BaseModel):
    """
    Decoded JWT claims, used internally by the auth dependency
    (backend.dependencies.auth.get_current_user) after verifying the
    token signature. Not returned directly in any API response.
    """

    sub: str = Field(..., description="Subject -- the user's UUID as a string")
    exp: int = Field(..., description="Expiry, Unix timestamp (seconds)")
