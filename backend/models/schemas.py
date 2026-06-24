# backend/models/schemas.py
"""
AIRP -- Pydantic Request/Response Schemas (T-046 / T-047)

Pydantic v2 models for the auth and analysis endpoints' request bodies
and response shapes. Kept in a separate module from backend/models/orm.py
because these are API contract schemas (validated at the HTTP boundary),
not database table definitions -- the two evolve independently and mixing
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
    "AnalysisStartRequest",
    "AnalysisStartResponse",
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
# Request schemas -- auth (T-046)
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
# Response schemas -- auth (T-046)
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


# ---------------------------------------------------------------------------
# Request schema -- analysis trigger (T-047)
# ---------------------------------------------------------------------------

#: Exchanges AIRP currently supports -- mirrors backend.models.orm.ExchangeEnum.
_VALID_EXCHANGES = frozenset({"NSE", "BSE"})


class AnalysisStartRequest(BaseModel):
    """
    Body for POST /api/v1/analysis/start.

    ``company_name`` is the only field most callers need to supply (e.g.
    'TCS' or 'Tata Consultancy Services') -- the service layer
    (backend.services.analysis) resolves it to a Yahoo Finance ticker via
    a deterministic lookup table, the same pattern already used by
    backend.agents.valuation_agent._ticker_to_slug. ``ticker`` and
    ``exchange`` are optional overrides for callers (e.g. a future
    autocomplete-driven frontend) that already know the exact Yahoo
    Finance symbol and want to skip resolution entirely.
    """

    company_name: str = Field(
        ...,
        min_length=1,
        max_length=300,
        description="Company name or ticker as typed by the user, e.g. 'TCS'",
    )
    ticker: Optional[str] = Field(
        default=None,
        max_length=40,
        description=(
            "Optional Yahoo Finance ticker override (e.g. 'TCS.NS'). "
            "When omitted, the service layer resolves company_name."
        ),
    )
    exchange: Optional[str] = Field(
        default=None,
        description="Optional exchange override: 'NSE' or 'BSE'.",
    )

    @field_validator("company_name")
    @classmethod
    def _reject_blank_company_name(cls, value: str) -> str:
        """Reject a company_name that is whitespace-only."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("company_name must not be empty or whitespace-only")
        return stripped

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: Optional[str]) -> Optional[str]:
        """Trim and uppercase an explicit ticker override, if provided."""
        if value is None:
            return None
        stripped = value.strip().upper()
        return stripped or None

    @field_validator("exchange")
    @classmethod
    def _validate_exchange(cls, value: Optional[str]) -> Optional[str]:
        """Reject an exchange override outside the supported set."""
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized not in _VALID_EXCHANGES:
            raise ValueError(
                f"exchange must be one of {sorted(_VALID_EXCHANGES)}, " f"got '{value}'"
            )
        return normalized


# ---------------------------------------------------------------------------
# Response schema -- analysis trigger (T-047)
# ---------------------------------------------------------------------------


class AnalysisStartResponse(BaseModel):
    """
    Body returned by POST /api/v1/analysis/start.

    Returned the moment the ``analyses`` row is committed and the
    LangGraph pipeline has been handed to FastAPI's BackgroundTasks --
    before any agent has actually run. Callers poll
    GET /api/v1/analysis/{job_id}/status (T-048) or open
    WS /api/v1/analysis/{job_id}/stream (T-049) to follow progress.
    """

    job_id: uuid.UUID = Field(description="UUID of the newly created analysis job")
    status: str = Field(description="Initial lifecycle status -- always 'pending'")
    company_name: str = Field(description="Resolved company display name")
    ticker: str = Field(description="Resolved Yahoo Finance ticker, e.g. 'TCS.NS'")
    exchange: str = Field(description="Resolved exchange -- 'NSE' or 'BSE'")
