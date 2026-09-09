# backend/migrations/versions/20260909_0000_a7b8c9d0e1f2_add_password_reset.py
"""add password_reset_tokens table and users.token_version

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-09 00:00:00.000000+00:00

B6 (refinement work order, bug #2): "Forgot / Reset Password" flow was
entirely missing -- backend/routers/auth.py had only
register/login/logout/me, with no way for a locked-out user to regain
access to their account.

``password_reset_tokens`` (new table)
------------------------------------------------------------------------
One row per requested reset. ``token_hash`` stores a SHA-256 hex digest
of the raw, randomly-generated reset token (see
backend.services.auth.generate_password_reset_token) -- the raw token
is only ever sent to the user (via email, or logged in a non-production
environment with no email service configured; see
backend.services.password_reset's own docstring) and is NEVER persisted
in plaintext, the same "never store the literal secret" principle
password_hash already applies to login passwords. A fast hash (SHA-256,
not bcrypt) is deliberate and correct here, unlike password_hash: the
raw token is already 256 bits of ``secrets.token_urlsafe`` randomness,
not a low-entropy human-chosen password -- bcrypt's deliberate slowness
defends against brute-forcing a guessable secret, which does not apply
to a value no human ever has to remember or type from memory.

``used_at`` (nullable) enforces single-use: NULL means still usable
(subject to ``expires_at``); set once
backend.services.password_reset.confirm_password_reset succeeds. A
NEW request also proactively marks every OTHER still-unused,
unexpired token for the same user as used (see that function's own
docstring) so an intercepted-but-stale reset email can never be
combined with a freshly-requested one to extend an attacker's window.

``users.token_version`` (new column)
------------------------------------------------------------------------
Every JWT issued by backend.services.auth.create_access_token now
carries the user's CURRENT token_version as a claim;
backend.dependencies.auth.get_current_user rejects a token whose
token_version claim does not match the row's current value. A
successful password reset increments this column, which is what
satisfies B6's "rotates sessions" requirement -- every access token
issued before the reset (e.g. a token an attacker who guessed/reused
the old password had captured) is immediately rejected on its very
next authenticated request, with no session-table/revocation-list
infrastructure needed for AIRP's otherwise-fully-stateless JWTs.
Defaults to 0 for every existing row so already-issued tokens (minted
before this migration, carrying no token_version claim at all --
backend.models.schemas.TokenPayload.token_version itself defaults to
0 when the claim is absent) continue to validate normally after
deploy; no forced mass logout.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users.token_version ──────────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment=(
                "Incremented on every successful password reset. A JWT's "
                "own token_version claim must match this value or "
                "get_current_user rejects it -- this is what invalidates "
                "every access token issued before a password reset "
                "(B6's 'rotate sessions' requirement)."
            ),
        ),
    )

    # ── Table: password_reset_tokens ─────────────────────────────────────
    op.create_table(
        "password_reset_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK → users.id — who requested this reset",
        ),
        sa.Column(
            "token_hash",
            sa.String(64),
            nullable=False,
            comment=(
                "SHA-256 hex digest of the raw reset token — the raw "
                "value itself is never stored, only ever emailed/logged "
                "once at request time (see this migration's own "
                "docstring for why SHA-256, not bcrypt, is correct here)"
            ),
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="UTC timestamp after which this token is no longer usable",
        ),
        sa.Column(
            "used_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="NULL until consumed (single-use) — set once a reset succeeds",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="UTC timestamp when this reset was requested",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="Single-use, expiring password-reset tokens (B6)",
    )
    op.create_index(
        "ix_password_reset_tokens_token_hash",
        "password_reset_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_password_reset_tokens_user_id",
        "password_reset_tokens",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_password_reset_tokens_user_id", table_name="password_reset_tokens"
    )
    op.drop_index(
        "ix_password_reset_tokens_token_hash", table_name="password_reset_tokens"
    )
    op.drop_table("password_reset_tokens")

    op.drop_column("users", "token_version")
