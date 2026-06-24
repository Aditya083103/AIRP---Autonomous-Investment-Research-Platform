# backend/services/auth.py
"""
AIRP -- Authentication Service (T-046)

Password hashing (bcrypt via passlib) and JWT issuance/verification for
self-hosted register/login/me endpoints. Pure business logic with no
FastAPI imports -- the router (backend/routers/auth.py) and the
get_current_user dependency (backend/dependencies/auth.py) both call
into this module, so it stays independently testable without spinning
up an ASGI app.

What this module does NOT do:
  * Touch the database directly -- callers pass in/receive plain values
    (password strings, User ORM instances) and persist them themselves.
  * Import FastAPI's HTTPException -- raises plain Python exceptions
    (InvalidCredentialsError, InvalidTokenError) that callers translate
    into the correct HTTP status code at the API boundary. Keeping HTTP
    concerns out of this module is what makes it testable in isolation.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

from jose import JWTError, jwt
from passlib.context import CryptContext

from backend.config import Settings, get_settings
from backend.models.schemas import TokenPayload

__all__ = [
    "InvalidCredentialsError",
    "InvalidTokenError",
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_access_token",
]

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

#: Single shared CryptContext instance -- passlib documents constructing
#: this once and reusing it, rather than per-call, since it caches the
#: configured bcrypt backend.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

#: JWT signing algorithm. HS256 (symmetric, shared-secret) is sufficient
#: here -- AIRP has one backend service issuing and verifying its own
#: tokens, not multiple services that would benefit from RS256's
#: asymmetric public/private key split.
_JWT_ALGORITHM = "HS256"


def hash_password(plain_password: str) -> str:
    """
    Return a bcrypt hash of ``plain_password``.

    Never raises for a well-formed string input -- length/emptiness
    validation belongs to the Pydantic request schema
    (UserRegisterRequest), not here.
    """
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """
    Return True if ``plain_password`` matches ``password_hash``.

    Never raises on a malformed/corrupt hash -- passlib's CryptContext
    can raise on some invalid hash strings, which is caught and treated
    as "does not match" so a corrupted password_hash value degrades to
    a failed login rather than a 500.
    """
    try:
        return bool(_pwd_context.verify(plain_password, password_hash))
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidCredentialsError(Exception):
    """Raised by the router when email/password does not match a user."""


class InvalidTokenError(Exception):
    """
    Raised by decode_access_token() for any unusable token: malformed,
    expired, wrong signature, or missing/invalid required claims.

    Deliberately one exception type for every failure mode -- the
    acceptance criterion is "invalid token returns 401", and a client
    should not be able to distinguish "expired" from "tampered" from
    the response, since that distinction has no legitimate use to a
    caller and a small information-disclosure cost to a token thief.
    """


# ---------------------------------------------------------------------------
# JWT issuance and verification
# ---------------------------------------------------------------------------


def create_access_token(
    user_id: uuid.UUID, settings: Settings | None = None
) -> tuple[str, int]:
    """
    Return (encoded_jwt, expires_in_minutes) for the given user.

    The token's ``sub`` claim is the user's UUID as a string (the JWT
    spec requires ``sub`` to be a string; the caller -- decode_access_token
    and get_current_user -- converts it back to a UUID). ``exp`` is a
    standard JWT claim consumed automatically by jose.jwt.decode's
    built-in expiry check.

    settings defaults to the process-wide cached Settings singleton via
    get_settings() when not supplied, so callers in request handlers
    don't need to thread it through manually; tests pass test_settings
    explicitly for isolation from the real environment.
    """
    resolved_settings = settings if settings is not None else get_settings()
    expire_minutes = resolved_settings.access_token_expire_minutes
    expire_at = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)

    claims: dict[str, Any] = {
        "sub": str(user_id),
        "exp": expire_at,
    }
    encoded = jwt.encode(claims, resolved_settings.secret_key, algorithm=_JWT_ALGORITHM)
    return encoded, expire_minutes


def decode_access_token(token: str, settings: Settings | None = None) -> TokenPayload:
    """
    Verify ``token``'s signature and expiry, and return its claims.

    Raises InvalidTokenError for every failure mode: bad signature,
    expired token, malformed token, or a token missing/mistyping the
    ``sub``/``exp`` claims. See InvalidTokenError's docstring for why
    these are not distinguished from each other.
    """
    resolved_settings = settings if settings is not None else get_settings()
    try:
        raw_claims = jwt.decode(
            token,
            resolved_settings.secret_key,
            algorithms=[_JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise InvalidTokenError("token signature or expiry check failed") from exc

    try:
        return TokenPayload.model_validate(raw_claims)
    except Exception as exc:
        # Pydantic ValidationError (or any other parsing failure) on a
        # token whose signature DID verify -- e.g. sub/exp missing or
        # the wrong type. Still an invalid token from the caller's
        # point of view, not a 500.
        raise InvalidTokenError("token claims are malformed") from exc
