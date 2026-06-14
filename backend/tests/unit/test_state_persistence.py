# backend/tests/unit/test_state_persistence.py
"""
Unit tests for T-033: State Persistence.

Acceptance criteria (from project plan):
  - Interrupted pipeline resumes from last saved node
  - State is visible in DB (mocked in unit tests; integration tests hit real DB)

Test strategy
-------------
  1. StatePersistenceService.save()
       success path -- returns True, commits, calls correct SQL
       no-row path  -- returns False when UPDATE affects 0 rows
       DB error     -- re-raises after rollback
  2. StatePersistenceService.load()
       snapshot exists    -- returns InvestmentState dict
       no row             -- returns None
       NULL snapshot      -- returns None
       dict snapshot      -- handles asyncpg JSONB-as-dict correctly
       str snapshot       -- handles psycopg2 JSONB-as-str correctly
       invalid JSON       -- returns None, logs error
       last_completed_node -- is read from DB row correctly
  3. StatePersistenceService.mark_failed()
       success -- commits, sets status=failed
       DB error -- re-raises after rollback
  4. Module-level persist_state()
       delegates to StatePersistenceService.save()
       patches AsyncSessionLocal so no real DB is used
  5. Module-level load_state()
       delegates to StatePersistenceService.load()
  6. _persist_after wrapper in nodes.py
       wraps a node function with persistence
       returns the node's partial dict unchanged
       calls persist_state with correct arguments
       swallows persistence errors (non-fatal)
       skips persistence when job_id is missing
  7. Persistence wrapper on every sequential node
       planner_node, research_join_node, error_handler_node,
       sentiment_escalation_node, risk_node, contrarian_node,
       valuation_node, portfolio_manager_node all call persist_state
  8. Parallel research nodes are NOT wrapped
       fundamental_node, technical_node, sentiment_node, macro_node
       do NOT call persist_state
  9. Resumption helper -- load_state returns last node name
 10. SQL constants are defined and non-empty
 11. Public API -- all symbols importable

All external calls (DB, LLMs, Redis, APIs) are mocked.
ENVIRONMENT must be set to 'test' before any backend import.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402

from backend.graph.state import InvestmentState, make_initial_state  # noqa: E402
from backend.services.state_persistence import (  # noqa: E402
    StatePersistenceService,
    load_state,
    persist_state,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_JOB_ID = "t033-test-job-uuid-001"
_COMPANY = "Tata Consultancy Services"
_TICKER = "TCS.NS"
_NODE = "planner"


def _make_state(**overrides: Any) -> InvestmentState:
    state = make_initial_state(
        job_id=_JOB_ID,
        company_name=_COMPANY,
        ticker=_TICKER,
        exchange="NSE",
        raw_query="TCS",
    )
    for key, value in overrides.items():
        state[key] = value  # type: ignore[literal-required]
    return state


def _make_mock_session(rowcount: int = 1) -> AsyncMock:
    """Return a mocked AsyncSession."""
    session = AsyncMock()

    # execute() returns a result object with .rowcount
    mock_result = MagicMock()
    mock_result.rowcount = rowcount
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _make_load_session(row: Any) -> AsyncMock:
    """Return a mocked AsyncSession that returns `row` from fetchone()."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone = MagicMock(return_value=row)
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# 1. StatePersistenceService.save()
# ---------------------------------------------------------------------------


class TestSaveSuccess:
    """save() returns True and commits on success."""

    def test_returns_true_on_one_row_affected(self) -> None:
        session = _make_mock_session(rowcount=1)
        svc = StatePersistenceService(session)
        state = _make_state(status="running")
        result = asyncio.run(svc.save(_JOB_ID, _NODE, state))
        assert result is True

    def test_calls_execute_once(self) -> None:
        session = _make_mock_session(rowcount=1)
        svc = StatePersistenceService(session)
        asyncio.run(svc.save(_JOB_ID, _NODE, _make_state()))
        session.execute.assert_called_once()

    def test_calls_commit(self) -> None:
        session = _make_mock_session(rowcount=1)
        svc = StatePersistenceService(session)
        asyncio.run(svc.save(_JOB_ID, _NODE, _make_state()))
        session.commit.assert_called_once()

    def test_does_not_rollback_on_success(self) -> None:
        session = _make_mock_session(rowcount=1)
        svc = StatePersistenceService(session)
        asyncio.run(svc.save(_JOB_ID, _NODE, _make_state()))
        session.rollback.assert_not_called()

    def test_passes_snapshot_json_to_execute(self) -> None:
        session = _make_mock_session(rowcount=1)
        svc = StatePersistenceService(session)
        state = _make_state(status="running")
        asyncio.run(svc.save(_JOB_ID, _NODE, state))
        call_kwargs = session.execute.call_args[0]
        params: dict[str, Any] = session.execute.call_args[0][1]
        assert "snapshot" in params
        # snapshot must be valid JSON
        parsed = json.loads(params["snapshot"])
        assert isinstance(parsed, dict)
        _ = call_kwargs  # silence unused warning

    def test_passes_node_name_to_execute(self) -> None:
        session = _make_mock_session(rowcount=1)
        svc = StatePersistenceService(session)
        asyncio.run(svc.save(_JOB_ID, "risk_officer", _make_state()))
        params: dict[str, Any] = session.execute.call_args[0][1]
        assert params["node_name"] == "risk_officer"

    def test_passes_job_id_to_execute(self) -> None:
        session = _make_mock_session(rowcount=1)
        svc = StatePersistenceService(session)
        asyncio.run(svc.save(_JOB_ID, _NODE, _make_state()))
        params: dict[str, Any] = session.execute.call_args[0][1]
        assert params["job_id"] == _JOB_ID

    def test_passes_status_from_state(self) -> None:
        session = _make_mock_session(rowcount=1)
        svc = StatePersistenceService(session)
        state = _make_state(status="completed")
        asyncio.run(svc.save(_JOB_ID, _NODE, state))
        params: dict[str, Any] = session.execute.call_args[0][1]
        assert params["status"] == "completed"

    def test_snapshot_contains_ticker(self) -> None:
        session = _make_mock_session(rowcount=1)
        svc = StatePersistenceService(session)
        asyncio.run(svc.save(_JOB_ID, _NODE, _make_state()))
        params: dict[str, Any] = session.execute.call_args[0][1]
        snap = json.loads(params["snapshot"])
        assert snap.get("ticker") == _TICKER

    def test_snapshot_contains_company_name(self) -> None:
        session = _make_mock_session(rowcount=1)
        svc = StatePersistenceService(session)
        asyncio.run(svc.save(_JOB_ID, _NODE, _make_state()))
        params: dict[str, Any] = session.execute.call_args[0][1]
        snap = json.loads(params["snapshot"])
        assert snap.get("company_name") == _COMPANY


class TestSaveNoRow:
    """save() returns False when UPDATE affects 0 rows."""

    def test_returns_false_when_no_row(self) -> None:
        session = _make_mock_session(rowcount=0)
        svc = StatePersistenceService(session)
        result = asyncio.run(svc.save(_JOB_ID, _NODE, _make_state()))
        assert result is False

    def test_still_commits_when_no_row(self) -> None:
        session = _make_mock_session(rowcount=0)
        svc = StatePersistenceService(session)
        asyncio.run(svc.save(_JOB_ID, _NODE, _make_state()))
        session.commit.assert_called_once()


class TestSaveDBError:
    """save() re-raises DB errors after rollback."""

    def test_re_raises_on_db_error(self) -> None:
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=RuntimeError("DB down"))
        svc = StatePersistenceService(session)
        with pytest.raises(RuntimeError, match="DB down"):
            asyncio.run(svc.save(_JOB_ID, _NODE, _make_state()))

    def test_calls_rollback_on_db_error(self) -> None:
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=RuntimeError("DB down"))
        svc = StatePersistenceService(session)
        try:
            asyncio.run(svc.save(_JOB_ID, _NODE, _make_state()))
        except RuntimeError:
            pass
        session.rollback.assert_called_once()

    def test_does_not_commit_on_db_error(self) -> None:
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=RuntimeError("DB down"))
        svc = StatePersistenceService(session)
        try:
            asyncio.run(svc.save(_JOB_ID, _NODE, _make_state()))
        except RuntimeError:
            pass
        session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# 2. StatePersistenceService.load()
# ---------------------------------------------------------------------------


class TestLoadSnapshotExists:
    """load() returns InvestmentState when snapshot exists."""

    def _make_snapshot_row(
        self,
        state: InvestmentState,
        last_node: str = "planner",
        status: str = "running",
    ) -> tuple[str, str, str]:
        return (json.dumps(dict(state), default=str), last_node, status)

    def test_returns_dict(self) -> None:
        state = _make_state()
        row = self._make_snapshot_row(state)
        session = _make_load_session(row)
        svc = StatePersistenceService(session)
        result = asyncio.run(svc.load(_JOB_ID))
        assert isinstance(result, dict)

    def test_returns_correct_ticker(self) -> None:
        state = _make_state()
        row = self._make_snapshot_row(state)
        session = _make_load_session(row)
        svc = StatePersistenceService(session)
        result = asyncio.run(svc.load(_JOB_ID))
        assert result is not None
        assert result.get("ticker") == _TICKER

    def test_returns_correct_job_id(self) -> None:
        state = _make_state()
        row = self._make_snapshot_row(state)
        session = _make_load_session(row)
        svc = StatePersistenceService(session)
        result = asyncio.run(svc.load(_JOB_ID))
        assert result is not None
        assert result.get("job_id") == _JOB_ID

    def test_handles_dict_snapshot_from_asyncpg(self) -> None:
        """asyncpg returns JSONB columns as Python dicts, not strings."""
        state = _make_state()
        # Simulate asyncpg returning a dict directly
        row = (dict(state), "planner", "running")
        session = _make_load_session(row)
        svc = StatePersistenceService(session)
        result = asyncio.run(svc.load(_JOB_ID))
        assert result is not None
        assert result.get("ticker") == _TICKER

    def test_handles_str_snapshot_from_psycopg2(self) -> None:
        """psycopg2 returns JSONB as a string."""
        state = _make_state()
        row = (json.dumps(dict(state)), "planner", "running")
        session = _make_load_session(row)
        svc = StatePersistenceService(session)
        result = asyncio.run(svc.load(_JOB_ID))
        assert result is not None
        assert result.get("ticker") == _TICKER

    def test_passes_job_id_to_execute(self) -> None:
        state = _make_state()
        row = self._make_snapshot_row(state)
        session = _make_load_session(row)
        svc = StatePersistenceService(session)
        asyncio.run(svc.load(_JOB_ID))
        params: dict[str, Any] = session.execute.call_args[0][1]
        assert params["job_id"] == _JOB_ID


class TestLoadNoRow:
    """load() returns None when no row exists."""

    def test_returns_none_when_no_row(self) -> None:
        session = _make_load_session(None)
        svc = StatePersistenceService(session)
        result = asyncio.run(svc.load(_JOB_ID))
        assert result is None

    def test_returns_none_when_snapshot_is_null(self) -> None:
        row = (None, "planner", "running")
        session = _make_load_session(row)
        svc = StatePersistenceService(session)
        result = asyncio.run(svc.load(_JOB_ID))
        assert result is None

    def test_returns_none_on_invalid_json(self) -> None:
        row = ("not-valid-json{{{", "planner", "running")
        session = _make_load_session(row)
        svc = StatePersistenceService(session)
        result = asyncio.run(svc.load(_JOB_ID))
        assert result is None

    def test_returns_none_when_snapshot_is_json_array(self) -> None:
        """Snapshot must be a JSON object, not an array."""
        row = ("[1, 2, 3]", "planner", "running")
        session = _make_load_session(row)
        svc = StatePersistenceService(session)
        result = asyncio.run(svc.load(_JOB_ID))
        assert result is None


class TestLoadDBError:
    """load() re-raises DB errors."""

    def test_re_raises_on_db_error(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=RuntimeError("connection lost"))
        svc = StatePersistenceService(session)
        with pytest.raises(RuntimeError, match="connection lost"):
            asyncio.run(svc.load(_JOB_ID))


# ---------------------------------------------------------------------------
# 3. StatePersistenceService.mark_failed()
# ---------------------------------------------------------------------------


class TestMarkFailed:
    """mark_failed() writes status=failed and commits."""

    def test_calls_execute(self) -> None:
        session = _make_mock_session(rowcount=1)
        svc = StatePersistenceService(session)
        asyncio.run(svc.mark_failed(_JOB_ID, "pipeline crashed", "contrarian_investor"))
        session.execute.assert_called_once()

    def test_commits(self) -> None:
        session = _make_mock_session(rowcount=1)
        svc = StatePersistenceService(session)
        asyncio.run(svc.mark_failed(_JOB_ID, "error", "planner"))
        session.commit.assert_called_once()

    def test_passes_error_message_to_execute(self) -> None:
        session = _make_mock_session(rowcount=1)
        svc = StatePersistenceService(session)
        error_msg = "fundamental_analyst raised ValueError"
        asyncio.run(svc.mark_failed(_JOB_ID, error_msg, "fundamental_analyst"))
        params: dict[str, Any] = session.execute.call_args[0][1]
        assert params["error_message"] == error_msg

    def test_re_raises_on_db_error(self) -> None:
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=RuntimeError("timeout"))
        svc = StatePersistenceService(session)
        with pytest.raises(RuntimeError):
            asyncio.run(svc.mark_failed(_JOB_ID, "error", "planner"))

    def test_rollback_on_db_error(self) -> None:
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=RuntimeError("timeout"))
        svc = StatePersistenceService(session)
        try:
            asyncio.run(svc.mark_failed(_JOB_ID, "error", "planner"))
        except RuntimeError:
            pass
        session.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Module-level persist_state()
# ---------------------------------------------------------------------------


class TestPersistStateModuleLevel:
    """persist_state() delegates to StatePersistenceService.save()."""

    def test_returns_true_on_success(self) -> None:
        mock_svc = AsyncMock()
        mock_svc.save = AsyncMock(return_value=True)
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "backend.services.state_persistence.StatePersistenceService",
                return_value=mock_svc,
            ),
            patch(
                "backend.db.session.AsyncSessionLocal",
                return_value=mock_session,
            ),
        ):
            result = asyncio.run(persist_state(_JOB_ID, _NODE, _make_state()))
        assert result is True

    def test_returns_false_when_no_row(self) -> None:
        mock_svc = AsyncMock()
        mock_svc.save = AsyncMock(return_value=False)
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "backend.services.state_persistence.StatePersistenceService",
                return_value=mock_svc,
            ),
            patch(
                "backend.db.session.AsyncSessionLocal",
                return_value=mock_session,
            ),
        ):
            result = asyncio.run(persist_state(_JOB_ID, _NODE, _make_state()))
        assert result is False

    def test_passes_correct_args_to_save(self) -> None:
        mock_svc = AsyncMock()
        mock_svc.save = AsyncMock(return_value=True)
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        state = _make_state(status="running")
        with (
            patch(
                "backend.services.state_persistence.StatePersistenceService",
                return_value=mock_svc,
            ),
            patch(
                "backend.db.session.AsyncSessionLocal",
                return_value=mock_session,
            ),
        ):
            asyncio.run(persist_state(_JOB_ID, "research_join", state))

        mock_svc.save.assert_called_once_with(
            job_id=_JOB_ID,
            node_name="research_join",
            state=state,
        )


# ---------------------------------------------------------------------------
# 5. Module-level load_state()
# ---------------------------------------------------------------------------


class TestLoadStateModuleLevel:
    """load_state() delegates to StatePersistenceService.load()."""

    def test_returns_state_on_hit(self) -> None:
        expected_state = _make_state(status="running")
        mock_svc = AsyncMock()
        mock_svc.load = AsyncMock(return_value=expected_state)
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "backend.services.state_persistence.StatePersistenceService",
                return_value=mock_svc,
            ),
            patch(
                "backend.db.session.AsyncSessionLocal",
                return_value=mock_session,
            ),
        ):
            result = asyncio.run(load_state(_JOB_ID))
        assert result is expected_state

    def test_returns_none_on_miss(self) -> None:
        mock_svc = AsyncMock()
        mock_svc.load = AsyncMock(return_value=None)
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "backend.services.state_persistence.StatePersistenceService",
                return_value=mock_svc,
            ),
            patch(
                "backend.db.session.AsyncSessionLocal",
                return_value=mock_session,
            ),
        ):
            result = asyncio.run(load_state(_JOB_ID))
        assert result is None

    def test_passes_job_id_to_load(self) -> None:
        mock_svc = AsyncMock()
        mock_svc.load = AsyncMock(return_value=None)
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "backend.services.state_persistence.StatePersistenceService",
                return_value=mock_svc,
            ),
            patch(
                "backend.db.session.AsyncSessionLocal",
                return_value=mock_session,
            ),
        ):
            asyncio.run(load_state("specific-job-xyz"))

        mock_svc.load.assert_called_once_with(job_id="specific-job-xyz")


# ---------------------------------------------------------------------------
# 6. _persist_after wrapper behaviour (via nodes.py)
# ---------------------------------------------------------------------------


class TestPersistAfterWrapper:
    """_persist_after wraps nodes correctly."""

    def _make_dummy_node(self, return_val: dict[str, Any]) -> Any:
        """Return a simple callable that returns return_val."""
        return MagicMock(return_value=return_val)

    def test_wrapper_returns_partial_dict_unchanged(self) -> None:
        from backend.graph.nodes import _persist_after

        partial = {"status": "running", "current_node": "planner"}
        wrapped = _persist_after(MagicMock(return_value=partial), "planner")
        state = _make_state()
        with patch("backend.graph.nodes._run_persist"):
            result = wrapped(state)
        assert result == partial

    def test_wrapper_calls_node_fn_once(self) -> None:
        from backend.graph.nodes import _persist_after

        mock_fn = MagicMock(return_value={"current_node": "planner"})
        wrapped = _persist_after(mock_fn, "planner")
        state = _make_state()
        with patch("backend.graph.nodes._run_persist"):
            wrapped(state)
        mock_fn.assert_called_once_with(state)

    def test_wrapper_calls_run_persist(self) -> None:
        from backend.graph.nodes import _persist_after

        mock_fn = MagicMock(return_value={"current_node": "planner"})
        wrapped = _persist_after(mock_fn, "planner")
        state = _make_state()
        with patch("backend.graph.nodes._run_persist") as mock_persist:
            wrapped(state)
        mock_persist.assert_called_once()

    def test_wrapper_passes_node_name_to_persist(self) -> None:
        from backend.graph.nodes import _persist_after

        mock_fn = MagicMock(return_value={"current_node": "risk_officer"})
        wrapped = _persist_after(mock_fn, "risk_officer")
        state = _make_state()
        with patch("backend.graph.nodes._run_persist") as mock_persist:
            wrapped(state)
        call_kwargs = mock_persist.call_args[1]
        assert call_kwargs["node_name"] == "risk_officer"

    def test_wrapper_passes_job_id_to_persist(self) -> None:
        from backend.graph.nodes import _persist_after

        mock_fn = MagicMock(return_value={"current_node": "planner"})
        wrapped = _persist_after(mock_fn, "planner")
        state = _make_state()
        with patch("backend.graph.nodes._run_persist") as mock_persist:
            wrapped(state)
        call_kwargs = mock_persist.call_args[1]
        assert call_kwargs["job_id"] == _JOB_ID

    def test_wrapper_swallows_persist_errors(self) -> None:
        """Persistence failures must not abort the pipeline.

        We patch _run_persist with side_effect=RuntimeError to simulate the
        case where even _run_persist itself raises (e.g. the function is
        monkeypatched in a test environment that raises unconditionally).
        The _persist_after wrapper must catch this and return the partial dict.
        """
        from backend.graph.nodes import _persist_after

        mock_fn = MagicMock(return_value={"current_node": "planner"})
        wrapped = _persist_after(mock_fn, "planner")
        state = _make_state()
        with patch(
            "backend.graph.nodes._run_persist",
            side_effect=RuntimeError("DB down"),
        ):
            # Must NOT raise -- the wrapper's try/except catches _run_persist errors
            result = wrapped(state)
        assert result == {"current_node": "planner"}

    def test_wrapper_skips_persist_when_no_job_id(self) -> None:
        from backend.graph.nodes import _persist_after

        mock_fn = MagicMock(return_value={"current_node": "planner"})
        wrapped = _persist_after(mock_fn, "planner")
        empty_state: InvestmentState = cast(InvestmentState, {})
        with patch("backend.graph.nodes._run_persist") as mock_persist:
            wrapped(empty_state)
        mock_persist.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Sequential nodes all call persist_state
# ---------------------------------------------------------------------------


class TestSequentialNodesPersist:
    """Every sequential node calls _run_persist once."""

    def _assert_node_calls_persist(self, node_fn: Any, state: InvestmentState) -> None:
        with patch("backend.graph.nodes._run_persist") as mock_persist:
            node_fn(state)
        mock_persist.assert_called_once()

    def test_planner_node_calls_persist(self) -> None:
        from backend.graph.nodes import planner_node

        self._assert_node_calls_persist(planner_node, _make_state())

    def test_research_join_node_calls_persist(self) -> None:
        from backend.graph.nodes import research_join_node

        self._assert_node_calls_persist(research_join_node, _make_state())

    def test_error_handler_node_calls_persist(self) -> None:
        from backend.graph.nodes import error_handler_node

        state = _make_state(fundamental={"agent_name": "fa", "error": "timeout"})
        self._assert_node_calls_persist(error_handler_node, state)

    def test_sentiment_escalation_node_calls_persist(self) -> None:
        from backend.graph.nodes import sentiment_escalation_node

        state = _make_state(sentiment={"agent_name": "sa", "sentiment_score": -0.95})
        self._assert_node_calls_persist(sentiment_escalation_node, state)

    def test_risk_node_calls_persist(self) -> None:
        from backend.graph.nodes import risk_node

        self._assert_node_calls_persist(risk_node, _make_state())

    def test_contrarian_node_calls_persist(self) -> None:
        from backend.graph.nodes import contrarian_node

        self._assert_node_calls_persist(contrarian_node, _make_state())

    def test_valuation_node_calls_persist(self) -> None:
        from backend.graph.nodes import valuation_node

        self._assert_node_calls_persist(valuation_node, _make_state())

    def test_portfolio_manager_node_calls_persist(self) -> None:
        from backend.graph.nodes import portfolio_manager_node

        self._assert_node_calls_persist(portfolio_manager_node, _make_state())


# ---------------------------------------------------------------------------
# 8. Parallel research nodes do NOT call persist_state
# ---------------------------------------------------------------------------


class TestParallelNodesNoPersist:
    """Parallel research nodes must NOT call persist_state."""

    def _assert_node_no_persist(self, node_fn: Any, state: InvestmentState) -> None:
        with patch("backend.graph.nodes._run_persist") as mock_persist:
            node_fn(state)
        mock_persist.assert_not_called()

    def test_fundamental_node_no_persist(self) -> None:
        from backend.graph.nodes import fundamental_node

        mock_result = {"fundamental": {"agent_name": "fa", "score": 7}}
        with patch(
            "backend.graph.nodes.run_fundamental_analysis",
            return_value=mock_result,
        ):
            self._assert_node_no_persist(fundamental_node, _make_state())

    def test_technical_node_no_persist(self) -> None:
        from backend.graph.nodes import technical_node

        mock_result = {"technical": {"agent_name": "ta", "signal": "BUY"}}
        with patch(
            "backend.graph.nodes.run_technical_analysis",
            return_value=mock_result,
        ):
            self._assert_node_no_persist(technical_node, _make_state())

    def test_sentiment_node_no_persist(self) -> None:
        from backend.graph.nodes import sentiment_node

        mock_result = {"sentiment": {"agent_name": "sa", "sentiment_score": 0.3}}
        with patch(
            "backend.graph.nodes.run_sentiment_analysis",
            return_value=mock_result,
        ):
            self._assert_node_no_persist(sentiment_node, _make_state())

    def test_macro_node_no_persist(self) -> None:
        from backend.graph.nodes import macro_node

        mock_result = {"macro": {"agent_name": "ma", "macro_environment": "neutral"}}
        with patch(
            "backend.graph.nodes.run_macro_analysis",
            return_value=mock_result,
        ):
            self._assert_node_no_persist(macro_node, _make_state())


# ---------------------------------------------------------------------------
# 9. Resumption -- load_state returns last_completed_node info
# ---------------------------------------------------------------------------


class TestResumption:
    """load() returns state with enough info to resume from last node."""

    def test_returned_state_has_last_completed_node_in_current_node(self) -> None:
        state = _make_state(current_node="risk_officer")
        row = (json.dumps(dict(state), default=str), "risk_officer", "running")
        session = _make_load_session(row)
        svc = StatePersistenceService(session)
        result = asyncio.run(svc.load(_JOB_ID))
        assert result is not None
        assert result.get("current_node") == "risk_officer"

    def test_returned_state_preserves_fundamental_output(self) -> None:
        state = _make_state()
        state["fundamental"] = {"agent_name": "fa", "score": 8}
        row = (json.dumps(dict(state), default=str), "research_join", "running")
        session = _make_load_session(row)
        svc = StatePersistenceService(session)
        result = asyncio.run(svc.load(_JOB_ID))
        assert result is not None
        fund = result.get("fundamental")
        assert isinstance(fund, dict)
        assert fund.get("score") == 8

    def test_returned_state_preserves_risk_flags(self) -> None:
        state = _make_state()
        state["risk_flags"] = ["FUNDAMENTAL_DATA_UNAVAILABLE"]
        row = (
            json.dumps(dict(state), default=str),
            "error_handler",
            "running",
        )
        session = _make_load_session(row)
        svc = StatePersistenceService(session)
        result = asyncio.run(svc.load(_JOB_ID))
        assert result is not None
        flags = result.get("risk_flags", [])
        assert "FUNDAMENTAL_DATA_UNAVAILABLE" in flags

    def test_none_returned_when_no_snapshot(self) -> None:
        """If no checkpoint, runner starts pipeline from scratch."""
        session = _make_load_session(None)
        svc = StatePersistenceService(session)
        result = asyncio.run(svc.load(_JOB_ID))
        assert result is None


# ---------------------------------------------------------------------------
# 10. SQL constants
# ---------------------------------------------------------------------------


class TestSQLConstants:
    """_SQL_UPSERT_SNAPSHOT and _SQL_LOAD_SNAPSHOT are non-empty."""

    def test_upsert_sql_is_non_empty(self) -> None:
        from backend.services.state_persistence import _SQL_UPSERT_SNAPSHOT

        sql_text = str(_SQL_UPSERT_SNAPSHOT)
        assert len(sql_text) > 20

    def test_upsert_sql_contains_update(self) -> None:
        from backend.services.state_persistence import _SQL_UPSERT_SNAPSHOT

        assert "UPDATE" in str(_SQL_UPSERT_SNAPSHOT).upper()

    def test_upsert_sql_contains_state_snapshot(self) -> None:
        from backend.services.state_persistence import _SQL_UPSERT_SNAPSHOT

        assert "state_snapshot" in str(_SQL_UPSERT_SNAPSHOT)

    def test_upsert_sql_contains_last_completed_node(self) -> None:
        from backend.services.state_persistence import _SQL_UPSERT_SNAPSHOT

        assert "last_completed_node" in str(_SQL_UPSERT_SNAPSHOT)

    def test_load_sql_is_non_empty(self) -> None:
        from backend.services.state_persistence import _SQL_LOAD_SNAPSHOT

        sql_text = str(_SQL_LOAD_SNAPSHOT)
        assert len(sql_text) > 20

    def test_load_sql_contains_select(self) -> None:
        from backend.services.state_persistence import _SQL_LOAD_SNAPSHOT

        assert "SELECT" in str(_SQL_LOAD_SNAPSHOT).upper()

    def test_load_sql_contains_state_snapshot(self) -> None:
        from backend.services.state_persistence import _SQL_LOAD_SNAPSHOT

        assert "state_snapshot" in str(_SQL_LOAD_SNAPSHOT)


# ---------------------------------------------------------------------------
# 11. Public API
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """All public symbols importable from state_persistence module."""

    def test_service_class_importable(self) -> None:
        from backend.services.state_persistence import (  # noqa: F401
            StatePersistenceService,
        )

        assert StatePersistenceService is not None

    def test_persist_state_importable(self) -> None:
        from backend.services.state_persistence import persist_state  # noqa: F401

        assert persist_state is not None

    def test_load_state_importable(self) -> None:
        from backend.services.state_persistence import load_state  # noqa: F401

        assert load_state is not None

    def test_all_exports_present(self) -> None:
        import backend.services.state_persistence as m

        for sym in m.__all__:
            assert hasattr(m, sym), f"Missing: {sym}"

    def test_service_has_save_method(self) -> None:
        from backend.services.state_persistence import StatePersistenceService

        assert callable(getattr(StatePersistenceService, "save", None))

    def test_service_has_load_method(self) -> None:
        from backend.services.state_persistence import StatePersistenceService

        assert callable(getattr(StatePersistenceService, "load", None))

    def test_service_has_mark_failed_method(self) -> None:
        from backend.services.state_persistence import StatePersistenceService

        assert callable(getattr(StatePersistenceService, "mark_failed", None))
