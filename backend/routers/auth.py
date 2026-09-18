# backend/routers/auth.py
"""
AIRP -- Auth Router (T-046, extended in T-056 and B6)

POST /auth/register, POST /auth/login, POST /auth/logout, GET /auth/me,
POST /auth/password-reset/request, POST /auth/password-reset/confirm.

Acceptance criteria (from task spec):
  * Register -> login -> access protected route works end-to-end
  * Invalid token returns 401

Business logic (password hashing, JWT encode/decode) lives in
backend.services.auth; this module only handles the HTTP-layer
concerns -- request validation (via Pydantic schemas), database
queries, and translating service-layer exceptions into HTTP responses.

T-056 (React auth pages) note on cookies
-----------------------------------------
register() and login() now ALSO set an httpOnly cookie carrying the
same JWT the JSON body returns, so the browser holds a copy that is
not readable by JavaScript. This is deliberately additive:
GET /auth/me and every other protected route still authenticate via
the Authorization header ONLY (get_current_user is unchanged) -- the
frontend's WebSocket hook (useAnalysisStream, T-049) needs the raw
token value in JS to send it as a `?token=` query parameter (browsers
cannot attach custom headers to a WebSocket handshake), so the token
must stay available in JS memory for that call regardless of the
cookie. The cookie exists for defense-in-depth today and as the
foundation for a future task to make GET /auth/me also accept it (so
a page refresh can silently restore a session without JS ever holding
the token) -- that consumption side is intentionally NOT implemented
here to avoid changing get_current_user's contract (and every existing
test that calls it directly) inside a frontend-focused task.

B6: POST /auth/password-reset/request always returns 200
------------------------------------------------------------------------
Bug #2 (refinement work order): there was no "forgot password" flow at
all. POST /auth/password-reset/request returns the SAME 200 response
(PasswordResetRequestResponse's own default generic message) whether
or not ``email`` matches a real, active account -- backend.services.
password_reset.create_password_reset_request already returns None
rather than raising for "no such user" specifically so this handler
never has anything to branch on that would let a caller (or an
attacker enumerating registered emails) tell the two cases apart.

When a real user IS found, the reset link is sent via
backend.services.email_service.send_password_reset_email if
``settings.email_service_configured``; otherwise it is LOGGED (at INFO)
for local/staging developer convenience when ENVIRONMENT is not
'production', or logged as an operator-facing WARNING with the token
itself withheld when it IS production (no reset-token secrets in
production logs, ever) -- see the request handler's own inline
comments for the exact three-way branch.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.db.session import get_async_session
from backend.dependencies.auth import get_current_user
from backend.dependencies.common import get_settings_dependency
from backend.models.orm import User
from backend.models.schemas import (
    PasswordResetConfirmRequest,
    PasswordResetConfirmResponse,
    PasswordResetRequestRequest,
    PasswordResetRequestResponse,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from backend.services.auth import create_access_token, hash_password, verify_password
from backend.services.email_service import send_password_reset_email
from backend.services.password_reset import (
    InvalidOrExpiredResetTokenError,
    confirm_password_reset,
    create_password_reset_request,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

#: Name of the httpOnly cookie set by register()/login() and cleared by
#: logout(). Not read by any dependency yet (see module docstring) --
#: exists so the browser has a JS-inaccessible copy of the token today,
#: ready for a future task to wire consumption of it into
#: get_current_user without any change to this constant or the cookie
#: itself.
ACCESS_TOKEN_COOKIE_NAME = "airp_access_token"  # nosec B105 -- name, not a password


def _set_access_token_cookie(
    response: Response,
    *,
    access_token: str,
    expires_in_minutes: int,
    settings: Settings,
) -> None:
    """
    Set ``ACCESS_TOKEN_COOKIE_NAME`` as a real httpOnly cookie on ``response``.

    ``secure`` follows ``settings.is_production`` -- the cookie is
    marked Secure (HTTPS-only) in production and left un-secured in
    local/test HTTP development, matching how ``Settings.is_production``
    already gates other environment-specific behaviour elsewhere in the
    backend.

    ``samesite`` is also environment-conditional (T-074 audit finding
    C7): ``"lax"`` in local/test development, where the frontend and
    backend share an origin behind the Vite dev proxy (see
    ``frontend/vite.config.ts``) or Docker Compose's nginx image, and
    ``"none"`` in production, where the actual deploy target is a
    cross-SITE split (Vercel frontend, Render backend) -- a browser never
    attaches a ``SameSite=Lax`` cookie to a cross-site XHR/fetch at all,
    which would make this cookie permanently inert in exactly the
    deployment shape it needs to work in. Per the Set-Cookie spec,
    ``SameSite=None`` requires ``Secure`` -- already true here since
    ``secure`` is tied to the same ``is_production`` check.
    """
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=settings.is_production,
        samesite="none" if settings.is_production else "lax",
        max_age=expires_in_minutes * 60,
        path="/",
    )


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
    response: Response,
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

    access_token, expires_in = create_access_token(
        user.id, settings=settings, token_version=user.token_version
    )
    _set_access_token_cookie(
        response,
        access_token=access_token,
        expires_in_minutes=expires_in,
        settings=settings,
    )
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
    response: Response,
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

    access_token, expires_in = create_access_token(
        user.id, settings=settings, token_version=user.token_version
    )
    _set_access_token_cookie(
        response,
        access_token=access_token,
        expires_in_minutes=expires_in,
        settings=settings,
    )
    return TokenResponse(
        access_token=access_token,
        expires_in_minutes=expires_in,
        user=UserResponse.model_validate(user),
    )


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear the access-token cookie",
    description=(
        "Clears the httpOnly cookie set by register()/login(). Does not "
        "require authentication and does not touch any server-side "
        "session state -- AIRP's JWTs are stateless, so 'logout' is "
        "purely a client-side (cookie deletion) concern. The frontend "
        "additionally drops its in-memory access token on the same "
        "action; this endpoint exists so the cookie is cleared too."
    ),
)
async def logout(response: Response) -> None:
    response.delete_cookie(key=ACCESS_TOKEN_COOKIE_NAME, path="/")


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


# ---------------------------------------------------------------------------
# POST /auth/password-reset/request
# ---------------------------------------------------------------------------


@router.post(
    "/password-reset/request",
    response_model=PasswordResetRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Request a password-reset link",
    description=(
        "Always returns 200 with the same generic message, whether or "
        "not `email` matches a real, active account -- see this "
        "router's own module docstring for why. If it does match, a "
        "single-use, expiring reset link is emailed (or logged, in a "
        "non-production environment with no email service configured)."
    ),
)
async def request_password_reset(
    body: PasswordResetRequestRequest,
    session: AsyncSession = Depends(get_async_session),
    settings: Settings = Depends(get_settings_dependency),
) -> PasswordResetRequestResponse:
    result = await create_password_reset_request(session, body.email, settings)

    if result is not None:
        base_url = settings.frontend_base_url.rstrip("/")
        reset_url = f"{base_url}/reset-password?token={result.raw_token}"

        if settings.email_service_configured:
            await send_password_reset_email(
                settings=settings, to_email=body.email, reset_url=reset_url
            )
        elif not settings.is_production:
            # Local/staging developer convenience ONLY -- see this
            # router's own module docstring. Never reachable when
            # ENVIRONMENT=production (the branch below handles that
            # case instead, withholding the raw token entirely).
            logger.info(
                "password_reset: no email service configured -- reset URL for "
                "%s: %s",
                body.email,
                reset_url,
            )
        else:
            # Production with no email service configured: this is a
            # real operational misconfiguration (the user cannot
            # complete the reset), but the raw token is NEVER written
            # to a production log -- see this router's own module
            # docstring's "no reset-token secrets in production logs"
            # guarantee.
            logger.warning(
                "password_reset: reset requested for %s but no email service "
                "is configured in production -- the user cannot complete "
                "this reset. Configure BREVO_API_KEY/SMTP_FROM_EMAIL.",
                body.email,
            )

    return PasswordResetRequestResponse()


# ---------------------------------------------------------------------------
# POST /auth/password-reset/confirm
# ---------------------------------------------------------------------------


@router.post(
    "/password-reset/confirm",
    response_model=PasswordResetConfirmResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete a password reset",
    description=(
        "Sets a new password for the account the given token was "
        "issued for, invalidates the token (single-use), and rotates "
        "the account's sessions -- every access token issued before "
        "this call stops working on its very next use. Returns 400 if "
        "the token is invalid, expired, or already used."
    ),
)
async def confirm_password_reset_endpoint(
    body: PasswordResetConfirmRequest,
    session: AsyncSession = Depends(get_async_session),
) -> PasswordResetConfirmResponse:
    try:
        await confirm_password_reset(session, body.token, body.new_password)
    except InvalidOrExpiredResetTokenError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This reset link is invalid or has expired. Please request a new one."
            ),
        ) from None

    return PasswordResetConfirmResponse()
