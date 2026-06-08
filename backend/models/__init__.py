# backend/models/__init__.py
"""
AIRP models package.

Imports all ORM classes so Alembic can discover every table from a single
``from backend.models import Base`` in ``env.py``.
"""

from backend.models.orm import (
    AgentOutput,
    Analysis,
    Base,
    Company,
    InvestmentMemo,
    User,
)

__all__ = [
    "Base",
    "User",
    "Company",
    "Analysis",
    "AgentOutput",
    "InvestmentMemo",
]
