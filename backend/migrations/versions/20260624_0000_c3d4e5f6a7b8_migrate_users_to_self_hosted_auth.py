"""migrate users table from Clerk identity to self-hosted auth

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-24 00:00:00.000000+00:00

T-046: Implement Auth with JWT.

The ``users`` table was originally designed around Clerk as the auth
provider: ``clerk_user_id`` was the canonical, unique identity column,
and ``email`` carried no uniqueness constraint of its own (Clerk owned
identity; AIRP just mirrored profile fields). T-046 replaces this with
self-hosted email/password authentication per the actual task
requirements (bcrypt-hashed passwords, self-issued JWTs), so:

``clerk_user_id`` (dropped)
    No longer meaningful -- there is no Clerk identity to mirror.
    Its unique index is dropped first, then the column itself.

``email`` (altered)
    Becomes the canonical identity column: a unique constraint and
    index are added so ``email`` can be used as the login lookup key,
    matching the role ``clerk_user_id`` used to play.

``password_hash`` (added)
    Stores a bcrypt hash (via passlib) of the user's password. Added
    NOT NULL with no server_default and no existing rows, since this
    project has no production data yet (pre-launch, local/Neon free
    tier dev database only) -- a real production migration with
    existing user rows would need a backfill strategy or a nullable
    column with an application-level enforcement window instead.

``is_active`` (added)
    Soft-disable flag for future account suspension without deleting
    analysis history; defaults to true for all existing/new rows.

Rollback safety: downgrade() reverses every change in this migration
back to the exact prior schema, including restoring clerk_user_id as
NOT NULL UNIQUE -- this will fail on downgrade if any row was created
under the new schema, since there is no Clerk ID to restore. This is
intentional: a downgrade past this revision is a contract violation
for self-hosted-auth ROWS and the failure should be loud, not silent.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- Drop the Clerk-identity column and its index/unique constraint -----
    op.drop_index("ix_users_clerk_user_id", table_name="users")
    op.drop_column("users", "clerk_user_id")

    # -- email becomes the canonical, unique identity column ----------------
    # The initial schema (T-016) created a non-unique index on email
    # ("ix_users_email") for lookups; drop it and replace with a unique
    # index so the same name continues to mean "the email lookup index"
    # rather than leaving a stale duplicate.
    op.drop_index("ix_users_email", table_name="users")
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # -- password_hash: bcrypt hash via passlib ------------------------------
    op.add_column(
        "users",
        sa.Column(
            "password_hash",
            sa.String(255),
            nullable=False,
            comment="bcrypt hash of the user's password (passlib CryptContext)",
        ),
    )

    # -- is_active: soft-disable flag ----------------------------------------
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="False disables login without deleting the account/history",
        ),
    )

    # -- Table comment no longer references Clerk ----------------------------
    op.execute(
        "COMMENT ON TABLE users IS "
        "'Local user registry — one row per registered user'"
    )


def downgrade() -> None:
    op.execute(
        "COMMENT ON TABLE users IS "
        "'Local user registry — one row per Clerk-authenticated user'"
    )

    op.drop_column("users", "is_active")
    op.drop_column("users", "password_hash")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.add_column(
        "users",
        sa.Column(
            "clerk_user_id",
            sa.String(128),
            nullable=False,
            comment="Opaque Clerk user ID received from JWT (e.g. user_2abc...)",
        ),
    )
    op.create_index("ix_users_clerk_user_id", "users", ["clerk_user_id"], unique=True)
