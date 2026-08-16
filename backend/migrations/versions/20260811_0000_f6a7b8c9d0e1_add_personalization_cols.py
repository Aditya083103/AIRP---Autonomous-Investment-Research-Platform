# backend/migrations/versions/20260811_0000_f6a7b8c9d0e1_add_personalization_cols.py
"""add risk_appetite and preferred_sectors to user_preferences

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-11 00:00:00.000000+00:00

T-106: AIRP Assistant personalization. Adds two columns to the
``user_preferences`` table T-099 already created:

    risk_appetite      — self-reported investing risk tolerance
                          ('conservative' | 'moderate' | 'aggressive').
                          Nullable, no default: NULL means "not yet
                          known" -- the AIRP Assistant asks for this
                          once (backend/services/chat_llm.py's
                          ``build_personalization_instruction``) and
                          backend/routers/chat_stream.py persists it
                          the first time backend/services/
                          preference_extractor.py recognises an answer
                          in the user's own words.
    preferred_sectors  — JSON array of sector names the user has said
                          they favour (e.g. ['IT', 'Banking &
                          Financials']). Not nullable, defaults to an
                          empty JSON array -- "not yet known" is
                          represented the same way
                          ``watchlist_tickers`` already represents
                          "no tickers yet" (T-099), for consistency
                          within the same table rather than mixing
                          NULL-means-empty and []-means-empty across
                          sibling JSONB columns.

Both columns are used ONLY to adjust the AIRP Assistant's chat tone and
emphasis -- see chat_llm.py's SYSTEM_PROMPT hard rule -- never to alter
a stored BUY/HOLD/SELL verdict, conviction score, or price target. The
verdict-producing code path (backend/agents/portfolio_manager.py) does
not read this table and is untouched by this migration or by T-106.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    risk_appetite = postgresql.ENUM(
        "conservative",
        "moderate",
        "aggressive",
        name="risk_appetite",
        create_type=False,
    )
    risk_appetite.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "user_preferences",
        sa.Column(
            "risk_appetite",
            risk_appetite,
            nullable=True,
            comment=(
                "Self-reported risk tolerance: 'conservative' | 'moderate' "
                "| 'aggressive'. NULL until the assistant has asked and the "
                "user has answered once. Affects chat tone/emphasis ONLY."
            ),
        ),
    )
    op.add_column(
        "user_preferences",
        sa.Column(
            "preferred_sectors",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment=(
                "JSON array of sector names the user has said they favour "
                "(e.g. ['IT', 'Banking & Financials']). Empty until the "
                "assistant has asked and the user has answered once. "
                "Affects chat tone/emphasis ONLY."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_preferences", "preferred_sectors")
    op.drop_column("user_preferences", "risk_appetite")

    # 'risk_appetite' the ENUM TYPE is owned by this migration alone
    # (unlike 'exchange', which T-099's migration reused via
    # create_type=False) -- safe to drop unconditionally here.
    op.execute("DROP TYPE IF EXISTS risk_appetite")
