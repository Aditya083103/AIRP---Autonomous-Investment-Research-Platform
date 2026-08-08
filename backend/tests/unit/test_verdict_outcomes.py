# backend/tests/unit/test_verdict_outcomes.py
"""
Unit tests for the ``verdict_outcomes`` ORM model — T-087.

All tests run fully offline — no real database connection is required.
SQLAlchemy metadata inspection and model construction are used instead,
matching the pattern established in ``test_orm_models.py`` (T-016).

Test coverage (acceptance criteria from T-087):
  ✓ VerdictOutcome is importable from backend.models
  ✓ verdict_outcomes appears in Base.metadata alongside the other 5 tables
  ✓ Every column from the task spec exists with the correct type:
      analysis_id (FK), ticker, verdict, conviction_score,
      price_at_verdict, verdict_date, evaluation_horizon_days,
      price_at_evaluation, price_change_pct, directional_correct,
      evaluated_at
  ✓ analysis_id is a foreign key to analyses.id with ON DELETE CASCADE
  ✓ Required-at-verdict-time columns are NOT NULL
  ✓ Outcome columns (populated only after evaluation) are nullable
  ✓ (analysis_id, evaluation_horizon_days) unique constraint exists,
    allowing multiple evaluation horizons per analysis
  ✓ Supporting indexes exist (ticker, verdict_date)
  ✓ Analysis.verdict_outcomes relationship is declared with
    cascade="all, delete-orphan"
  ✓ VerdictOutcome.analysis back-reference is declared
  ✓ __repr__ returns a non-empty, informative string
  ✓ A VerdictOutcome instance can be constructed with only the
    verdict-time fields (outcome fields default to None pre-evaluation)

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_verdict_outcomes.py -v
"""

from __future__ import annotations

import os  # noqa: E402

os.environ.setdefault("ENVIRONMENT", "test")

from datetime import datetime, timezone  # noqa: E402
from typing import Any, cast  # noqa: E402
import uuid  # noqa: E402

from sqlalchemy import Boolean, Numeric, inspect as sa_inspect  # noqa: E402
from sqlalchemy.dialects.postgresql import UUID  # noqa: E402
from sqlalchemy.orm import RelationshipProperty  # noqa: E402

from backend.models import Analysis, Base, VerdictOutcome  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers (mirrors test_orm_models.py)
# ---------------------------------------------------------------------------


def _col(model: Any, name: str) -> Any:
    """Return the SQLAlchemy Column object for a model attribute by name."""
    mapper = sa_inspect(model)
    return mapper.columns[name]


def _fks(model: Any) -> set[str]:
    """Return the set of FK target column strings for a model."""
    mapper = sa_inspect(model)
    result = set()
    for col in mapper.columns:
        for fk in col.foreign_keys:
            result.add(fk.target_fullname)
    return result


def _uqs(model: Any) -> list[Any]:
    """Return all UniqueConstraint objects on a model's table."""
    mapper = sa_inspect(model)
    return [
        c
        for c in mapper.persist_selectable.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]


def _indexes(model: Any) -> set[str]:
    """Return the set of index names declared on a model's table."""
    mapper = sa_inspect(model)
    return {ix.name for ix in mapper.persist_selectable.indexes if ix.name}


# ---------------------------------------------------------------------------
# Test: model importable and registered on Base.metadata
# ---------------------------------------------------------------------------


class TestModelImport:
    def test_verdict_outcome_importable(self) -> None:
        assert VerdictOutcome is not None

    def test_table_name(self) -> None:
        assert VerdictOutcome.__tablename__ == "verdict_outcomes"

    def test_present_in_metadata(self) -> None:
        assert "verdict_outcomes" in Base.metadata.tables


# ---------------------------------------------------------------------------
# Test: primary key
# ---------------------------------------------------------------------------


class TestPrimaryKey:
    def test_pk_is_uuid(self) -> None:
        col = _col(VerdictOutcome, "id")
        assert isinstance(col.type, UUID)
        assert col.primary_key is True

    def test_pk_has_server_default(self) -> None:
        assert _col(VerdictOutcome, "id").server_default is not None


# ---------------------------------------------------------------------------
# Test: foreign key — analysis_id
# ---------------------------------------------------------------------------


class TestAnalysisForeignKey:
    def test_analysis_id_fk_target(self) -> None:
        assert "analyses.id" in _fks(VerdictOutcome)

    def test_analysis_id_not_nullable(self) -> None:
        assert _col(VerdictOutcome, "analysis_id").nullable is False

    def test_analysis_id_cascade_on_delete(self) -> None:
        col = _col(VerdictOutcome, "analysis_id")
        fk = next(iter(col.foreign_keys))
        assert fk.ondelete == "CASCADE"


# ---------------------------------------------------------------------------
# Test: verdict-time columns (populated when the row is first written)
# ---------------------------------------------------------------------------


class TestVerdictTimeColumns:
    def test_ticker_not_nullable(self) -> None:
        assert _col(VerdictOutcome, "ticker").nullable is False

    def test_ticker_max_length(self) -> None:
        assert _col(VerdictOutcome, "ticker").type.length == 40

    def test_verdict_not_nullable(self) -> None:
        assert _col(VerdictOutcome, "verdict").nullable is False

    def test_conviction_score_not_nullable(self) -> None:
        assert _col(VerdictOutcome, "conviction_score").nullable is False

    def test_price_at_verdict_not_nullable(self) -> None:
        assert _col(VerdictOutcome, "price_at_verdict").nullable is False

    def test_price_at_verdict_is_numeric(self) -> None:
        assert isinstance(_col(VerdictOutcome, "price_at_verdict").type, Numeric)

    def test_verdict_date_not_nullable(self) -> None:
        assert _col(VerdictOutcome, "verdict_date").nullable is False

    def test_evaluation_horizon_days_not_nullable(self) -> None:
        assert _col(VerdictOutcome, "evaluation_horizon_days").nullable is False


# ---------------------------------------------------------------------------
# Test: outcome columns (NULL until the evaluation job runs)
# ---------------------------------------------------------------------------


class TestOutcomeColumns:
    def test_price_at_evaluation_nullable(self) -> None:
        assert _col(VerdictOutcome, "price_at_evaluation").nullable is True

    def test_price_at_evaluation_is_numeric(self) -> None:
        assert isinstance(_col(VerdictOutcome, "price_at_evaluation").type, Numeric)

    def test_price_change_pct_nullable(self) -> None:
        assert _col(VerdictOutcome, "price_change_pct").nullable is True

    def test_price_change_pct_is_numeric(self) -> None:
        assert isinstance(_col(VerdictOutcome, "price_change_pct").type, Numeric)

    def test_directional_correct_nullable(self) -> None:
        assert _col(VerdictOutcome, "directional_correct").nullable is True

    def test_directional_correct_is_boolean(self) -> None:
        assert isinstance(_col(VerdictOutcome, "directional_correct").type, Boolean)

    def test_evaluated_at_nullable(self) -> None:
        assert _col(VerdictOutcome, "evaluated_at").nullable is True


# ---------------------------------------------------------------------------
# Test: constraints and indexes
# ---------------------------------------------------------------------------


class TestConstraintsAndIndexes:
    def test_unique_constraint_analysis_horizon(self) -> None:
        uqs = _uqs(VerdictOutcome)
        uq_names = {uq.name for uq in uqs if uq.name}
        assert "uq_verdict_outcomes_analysis_horizon" in uq_names

    def test_unique_constraint_covers_both_columns(self) -> None:
        uqs = _uqs(VerdictOutcome)
        target = next(
            uq for uq in uqs if uq.name == "uq_verdict_outcomes_analysis_horizon"
        )
        col_names = {c.name for c in target.columns}
        assert col_names == {"analysis_id", "evaluation_horizon_days"}

    def test_ticker_index_present(self) -> None:
        assert "ix_verdict_outcomes_ticker" in _indexes(VerdictOutcome)

    def test_verdict_date_index_present(self) -> None:
        assert "ix_verdict_outcomes_verdict_date" in _indexes(VerdictOutcome)


# ---------------------------------------------------------------------------
# Test: relationships
# ---------------------------------------------------------------------------


class TestRelationships:
    def _rel(self, model: Any, name: str) -> "RelationshipProperty[Any]":
        mapper = sa_inspect(model)
        return cast("RelationshipProperty[Any]", mapper.relationships[name])

    def test_analysis_has_verdict_outcomes_relationship(self) -> None:
        rel = self._rel(Analysis, "verdict_outcomes")
        assert rel is not None

    def test_analysis_verdict_outcomes_cascade_delete_orphan(self) -> None:
        rel = self._rel(Analysis, "verdict_outcomes")
        assert "delete-orphan" in str(rel.cascade)

    def test_analysis_verdict_outcomes_is_list(self) -> None:
        # One analysis can have multiple evaluation-horizon rows
        rel = self._rel(Analysis, "verdict_outcomes")
        assert rel.uselist is True

    def test_verdict_outcome_has_analysis_relationship(self) -> None:
        rel = self._rel(VerdictOutcome, "analysis")
        assert rel is not None


# ---------------------------------------------------------------------------
# Test: __repr__ and construction
# ---------------------------------------------------------------------------


class TestReprAndConstruction:
    def test_repr_contains_key_fields(self) -> None:
        vo = VerdictOutcome(
            analysis_id=uuid.uuid4(),
            ticker="TCS.NS",
            verdict="BUY",
            evaluation_horizon_days=30,
        )
        text = repr(vo)
        assert "VerdictOutcome" in text
        assert "TCS.NS" in text
        assert "BUY" in text
        assert "30" in text

    def test_construct_with_only_verdict_time_fields(self) -> None:
        # Outcome fields are unset (None) before the evaluation job runs —
        # this must not raise at construction time (DB-level NOT NULL
        # constraints only apply once flushed to a real database).
        vo = VerdictOutcome(
            analysis_id=uuid.uuid4(),
            ticker="INFY.NS",
            verdict="HOLD",
            conviction_score=6,
            price_at_verdict=1500.25,
            verdict_date=datetime.now(timezone.utc),
            evaluation_horizon_days=90,
        )
        assert vo.price_at_evaluation is None
        assert vo.price_change_pct is None
        assert vo.directional_correct is None
        assert vo.evaluated_at is None
