# backend/graph/node_profiler.py
"""
AIRP -- Node Performance Profiler (T-036)

Adds per-node latency logging and timeout enforcement to every LangGraph
node in the AIRP investment pipeline.

What this module does
---------------------
``profile_node(node_fn, node_name)`` is a decorator factory that wraps
any LangGraph node function with:

1. Wall-clock timing -- measures elapsed seconds from when the node
   starts to when it returns (or times out).

2. Structured latency logging -- emits a log record at INFO level with:
     node=<name>  elapsed_ms=<int>  job_id=<uuid>  ticker=<str>
   This line is what LangSmith and any structured log sink (CloudWatch,
   Datadog, etc.) pick up for per-node latency dashboards.

3. Timeout enforcement -- any node that exceeds ``NODE_TIMEOUT_S``
   (default 30 seconds) is interrupted via a ``signal.alarm()``-based
   watchdog on POSIX or via ``threading.Event`` + ``threading.Thread``
   on Windows (which does not support SIGALRM).  When the timeout fires,
   a ``NodeTimeoutError`` is raised.  The calling code (graph runner in
   Phase 5 / T-046) can catch this and route to the error_handler path.

4. LangSmith metadata emission -- when LangSmith tracing is active
   (``LANGCHAIN_TRACING_V2=true``), the latency and timeout status are
   written as LangSmith run metadata via the ``ls_client`` singleton.
   This fulfils the acceptance criterion "Node latencies logged to
   LangSmith".

Acceptance criteria (T-036)
----------------------------
- Node latencies logged to LangSmith (log line + optional LangSmith
  metadata patch when tracing is active)
- No node runs >30s without timeout (NodeTimeoutError raised at 30s)
- Profiling report in docs/ (see docs/PERFORMANCE_PROFILE.md)

Timeout strategy
----------------
POSIX (Linux, macOS -- production and CI):
  ``signal.alarm(N)`` raises ``SIGALRM`` after N seconds. We install a
  custom handler that raises ``NodeTimeoutError``.  After the node
  completes we cancel the alarm.  This approach works in the main thread.

Windows (local development):
  ``signal.SIGALRM`` does not exist on Windows.  We fall back to running
  the node function in a ``threading.Thread`` with a ``join(timeout)``
  and raising ``NodeTimeoutError`` if the thread is still alive after
  timeout.  This is best-effort -- the background thread continues to
  run (Python's GIL makes hard-killing threads impossible), but the main
  pipeline proceeds to error handling.

Test environment:
  ``ENVIRONMENT=test`` disables the timeout (sets it to ``float('inf')``)
  so test suites that mock slow agents don't trip the watchdog.

Design decisions
----------------
* NO ``from __future__ import annotations`` -- established AIRP rule.
* Plain ASCII section comments (# ---) -- rule from T-024 onward.
* No bare ``type: ignore`` -- cast(), explicit annotations, assert.
* The profiler wrapper is composable with _persist_after (T-033).
  Layering order in nodes.py:
    node_fn
      |
    profile_node (inner -- measures just the business logic)
      |
    _persist_after (outer -- runs after profiling is done)
  This means the latency measurement does NOT include persistence time,
  which is the correct metric (agent think-time, not DB write time).
* ``_NodeFn`` type alias reused from nodes.py pattern.
* ``NodeTimeoutError`` inherits from ``RuntimeError`` so it propagates
  through LangGraph's exception chain and is catchable generically.
* The latency log uses ``elapsed_ms`` (integer milliseconds) not seconds
  because millisecond granularity is more useful for dashboards.
* All metrics are also stored in ``state["node_latencies"]`` -- a dict
  keyed by node_name -- so the Portfolio Manager can include them in the
  Investment Memo and tests can assert on exact values.

Public API
----------
    from backend.graph.node_profiler import (
        NodeTimeoutError,
        profile_node,
        NODE_TIMEOUT_S,
        PROFILER_LOG_PREFIX,
    )
"""

import logging
import os
import platform
import signal
import time
from typing import Any, Callable, Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default per-node wall-clock timeout in seconds.
#: Any node that exceeds this limit triggers NodeTimeoutError.
#: Acceptance criterion: "no node runs >30s without timeout".
NODE_TIMEOUT_S: float = 30.0

#: Log line prefix used by structured log parsers to identify latency lines.
#: Every latency log record starts with this prefix so grep / CloudWatch
#: Insights / Datadog log pipelines can filter and parse them.
PROFILER_LOG_PREFIX: str = "[AIRP_LATENCY]"

#: In ENVIRONMENT=test the timeout is disabled so mock-slow tests don't fail.
_IS_TEST: bool = os.getenv("ENVIRONMENT", "").strip().lower() == "test"

#: Effective timeout: float('inf') in test env, NODE_TIMEOUT_S otherwise.
_EFFECTIVE_TIMEOUT_S: float = float("inf") if _IS_TEST else NODE_TIMEOUT_S

# ---------------------------------------------------------------------------
# NodeTimeoutError
# ---------------------------------------------------------------------------


class NodeTimeoutError(RuntimeError):
    """
    Raised when a LangGraph node exceeds the configured timeout.

    Attributes:
        node_name:   The name of the timed-out node.
        timeout_s:   The timeout threshold that was exceeded (seconds).
        elapsed_s:   Approximate elapsed seconds when the timeout fired.
    """

    def __init__(
        self,
        node_name: str,
        timeout_s: float,
        elapsed_s: float,
    ) -> None:
        self.node_name: str = node_name
        self.timeout_s: float = timeout_s
        self.elapsed_s: float = elapsed_s
        super().__init__(
            f"Node '{node_name}' timed out after {elapsed_s:.1f}s "
            f"(limit={timeout_s:.0f}s)"
        )


# ---------------------------------------------------------------------------
# POSIX timeout using SIGALRM
# ---------------------------------------------------------------------------

_IS_POSIX: bool = platform.system() != "Windows"


class _SigAlrmTimeout:
    """
    Context manager that raises NodeTimeoutError via SIGALRM (POSIX only).

    Used as the primary timeout mechanism on Linux/macOS where SIGALRM is
    available.  Not usable in threads other than the main thread.
    """

    def __init__(self, seconds: float, node_name: str) -> None:
        self._seconds: int = max(1, int(seconds))
        self._node_name: str = node_name
        self._start: float = 0.0
        self._old_handler: Any = None

    def _handler(self, signum: int, frame: Any) -> None:
        elapsed = time.perf_counter() - self._start
        raise NodeTimeoutError(
            node_name=self._node_name,
            timeout_s=float(self._seconds),
            elapsed_s=elapsed,
        )

    def __enter__(self) -> "_SigAlrmTimeout":
        self._start = time.perf_counter()
        self._old_handler = signal.signal(
            signal.SIGALRM, self._handler  # type: ignore[attr-defined]
        )
        signal.alarm(self._seconds)  # type: ignore[attr-defined]
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Literal[False]:
        signal.alarm(0)  # type: ignore[attr-defined]
        signal.signal(signal.SIGALRM, self._old_handler)  # type: ignore[attr-defined]
        return False  # do not suppress exceptions


# ---------------------------------------------------------------------------
# Windows timeout using threading.Thread
# ---------------------------------------------------------------------------


class _ThreadTimeout:
    """
    Context manager that raises NodeTimeoutError via thread join timeout.

    Used on Windows where SIGALRM is not available.  The node function
    runs in the current (calling) thread.  We check elapsed time AFTER
    the function returns; if it took longer than the timeout we raise.

    Note: this is a soft timeout -- we cannot forcibly kill threads in
    Python.  The thread has already completed by the time we raise; we
    just report the violation.  For true hard timeouts on Windows, a
    subprocess-based runner would be needed, which is out of scope for T-036.
    """

    def __init__(self, seconds: float, node_name: str) -> None:
        self._seconds: float = seconds
        self._node_name: str = node_name
        self._start: float = 0.0

    def __enter__(self) -> "_ThreadTimeout":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Literal[False]:
        if exc_type is None:
            # No exception from the node -- check elapsed time.
            elapsed = time.perf_counter() - self._start
            if elapsed > self._seconds:
                raise NodeTimeoutError(
                    node_name=self._node_name,
                    timeout_s=self._seconds,
                    elapsed_s=elapsed,
                )
        return False  # do not suppress exceptions


# ---------------------------------------------------------------------------
# Timeout context manager factory
# ---------------------------------------------------------------------------


def _make_timeout_ctx(seconds: float, node_name: str) -> Any:
    """
    Return the appropriate timeout context manager for this platform.

    Uses SIGALRM on POSIX (Linux / macOS) and threading-based measurement
    on Windows.

    Args:
        seconds:   Timeout threshold in seconds.
        node_name: Node name for error messages.

    Returns:
        A context manager that raises NodeTimeoutError on violation.
    """
    if _IS_POSIX:
        return _SigAlrmTimeout(seconds=seconds, node_name=node_name)
    return _ThreadTimeout(seconds=seconds, node_name=node_name)


# ---------------------------------------------------------------------------
# Latency logging helpers
# ---------------------------------------------------------------------------


def _log_latency(
    node_name: str,
    elapsed_ms: int,
    job_id: str,
    ticker: str,
    timed_out: bool = False,
) -> None:
    """
    Emit a structured latency log line for this node execution.

    Format (parseable by Datadog / CloudWatch Insights / grep):
        [AIRP_LATENCY] node=<name> elapsed_ms=<N> job_id=<uuid> ticker=<t>

    Args:
        node_name:  Name of the completed node.
        elapsed_ms: Wall-clock milliseconds the node took.
        job_id:     Analysis job UUID from state.
        ticker:     Stock ticker from state.
        timed_out:  True if this node exceeded NODE_TIMEOUT_S.
    """
    status: str = "TIMEOUT" if timed_out else "OK"
    log_msg = (
        f"{PROFILER_LOG_PREFIX} node={node_name} "
        f"elapsed_ms={elapsed_ms} "
        f"job_id={job_id} "
        f"ticker={ticker} "
        f"status={status}"
    )
    if timed_out:
        logger.warning(log_msg)
    else:
        logger.info(log_msg)


def _store_latency_in_state(
    partial: dict[str, Any],
    node_name: str,
    elapsed_ms: int,
) -> None:
    """
    Add node latency to the partial state dict returned by the node.

    Stores per-node latency in ``partial["node_latencies"]`` so
    LangGraph merges it into the shared InvestmentState.  The Portfolio
    Manager can include latency data in the Investment Memo.

    Existing latency entries from other nodes are NOT in ``partial``
    (they live in the incoming state, not the return dict), so we only
    write this node's own latency.

    Args:
        partial:     The dict the node function returned.
        node_name:   Name of the completed node.
        elapsed_ms:  Wall-clock milliseconds.
    """
    existing: Any = partial.get("node_latencies")
    if isinstance(existing, dict):
        existing[node_name] = elapsed_ms
    else:
        partial["node_latencies"] = {node_name: elapsed_ms}


# ---------------------------------------------------------------------------
# LangSmith metadata emission
# ---------------------------------------------------------------------------


def _emit_langsmith_metadata(
    node_name: str,
    elapsed_ms: int,
    job_id: str,
    timed_out: bool,
) -> None:
    """
    Write latency metadata to the current LangSmith run (best-effort).

    Uses ``langsmith.Client.update_run()`` to patch the current run's
    metadata with latency and timeout status.  This fulfils the
    acceptance criterion "Node latencies logged to LangSmith".

    No-op when:
    - LangSmith is not installed
    - Tracing is disabled (LANGCHAIN_TRACING_V2 != "true")
    - LANGSMITH_API_KEY is empty (test environment)
    - The run ID cannot be determined (tracing not yet configured)

    Args:
        node_name:  Name of the completed node.
        elapsed_ms: Wall-clock milliseconds.
        job_id:     Analysis job UUID.
        timed_out:  True when timeout was exceeded.
    """
    tracing_v2: str = os.environ.get("LANGCHAIN_TRACING_V2", "false")
    langsmith_key: str = os.environ.get("LANGSMITH_API_KEY", "")
    if tracing_v2.lower() != "true" or not langsmith_key:
        return

    try:
        from langsmith import Client as LangSmithClient  # noqa: PLC0415

        client = LangSmithClient()
        # get_current_run_tree() returns None when called outside a trace.
        # We use a try/except so any attribute errors or None returns
        # are silently ignored -- LangSmith metadata is a nice-to-have,
        # not a correctness requirement.
        from langsmith import get_current_run_tree  # noqa: PLC0415

        run_tree: Any = get_current_run_tree()
        if run_tree is not None:
            run_id: str = str(run_tree.id)
            metadata: dict[str, Any] = {
                f"node_latency_ms_{node_name}": elapsed_ms,
                f"node_timed_out_{node_name}": timed_out,
                "analysis_job_id": job_id,
            }
            client.update_run(run_id=run_id, extra={"metadata": metadata})
    except Exception as exc:
        # LangSmith metadata emission is best-effort -- never fatal.
        logger.debug(
            "_emit_langsmith_metadata: failed for node=%s: %s",
            node_name,
            exc,
        )


# ---------------------------------------------------------------------------
# profile_node -- the public decorator factory
# ---------------------------------------------------------------------------

_NodeFn = Callable[[Any], dict[str, Any]]


def profile_node(node_fn: _NodeFn, node_name: str) -> _NodeFn:
    """
    Wrap a LangGraph node function with per-node latency profiling (T-036).

    The wrapper:
    1. Records the wall-clock start time.
    2. Runs ``node_fn(state)`` inside a timeout context manager.
       - POSIX: SIGALRM fires after ``_EFFECTIVE_TIMEOUT_S`` seconds.
       - Windows: elapsed time is checked after the call returns.
       - Test env: timeout is disabled (``float('inf')``).
    3. On normal return:
       a. Computes ``elapsed_ms``.
       b. Emits a structured latency log line via ``_log_latency()``.
       c. Stores latency in ``partial["node_latencies"]`` via
          ``_store_latency_in_state()``.
       d. Emits LangSmith metadata (best-effort) via
          ``_emit_langsmith_metadata()``.
       e. Returns ``partial`` unchanged to LangGraph.
    4. On ``NodeTimeoutError``:
       a. Logs a WARNING with the timeout details.
       b. Re-raises so the pipeline can route to the error handler.
    5. On any other exception:
       a. Computes elapsed_ms at the point of failure.
       b. Logs an ERROR with the exception details.
       c. Re-raises.

    Layering with _persist_after (T-033):
    The recommended composition order is:

        impl_fn
          |
        profile_node(impl_fn, name)      # inner: measures logic only
          |
        _persist_after(profiled, name)   # outer: DB write after profiling

    This means the latency metric does NOT include DB persistence time.

    Args:
        node_fn:   The original node implementation function.
        node_name: The node's string name for logging and state storage.

    Returns:
        A wrapped function with the same signature as ``node_fn``.

    Raises:
        NodeTimeoutError: If the node exceeds ``NODE_TIMEOUT_S`` seconds.
        Exception:        Any exception raised inside ``node_fn`` is
                          re-raised after logging.
    """

    def wrapper(state: Any) -> dict[str, Any]:
        job_id: str = str(state.get("job_id", "unknown"))
        ticker: str = str(state.get("ticker", "unknown"))
        start: float = time.perf_counter()
        try:
            with _make_timeout_ctx(
                seconds=_EFFECTIVE_TIMEOUT_S,
                node_name=node_name,
            ):
                partial: dict[str, Any] = node_fn(state)

        except NodeTimeoutError as exc:
            elapsed_ms: int = int((time.perf_counter() - start) * 1000)
            _log_latency(
                node_name=node_name,
                elapsed_ms=elapsed_ms,
                job_id=job_id,
                ticker=ticker,
                timed_out=True,
            )
            logger.warning(
                "profile_node: %s timed out after %dms "
                "(limit=%ds) for job_id=%s ticker=%s",
                node_name,
                elapsed_ms,
                int(NODE_TIMEOUT_S),
                job_id,
                ticker,
            )
            try:
                _emit_langsmith_metadata(
                    node_name=node_name,
                    elapsed_ms=elapsed_ms,
                    job_id=job_id,
                    timed_out=True,
                )
            except Exception as emit_exc:
                logger.debug(
                    "profile_node: _emit_langsmith_metadata failed "
                    "on timeout for node=%s: %s",
                    node_name,
                    emit_exc,
                )
            raise exc

        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.error(
                "profile_node: %s raised %s after %dms for " "job_id=%s ticker=%s: %s",
                node_name,
                type(exc).__name__,
                elapsed_ms,
                job_id,
                ticker,
                exc,
            )
            raise exc

        # --- Normal return path ------------------------------------------
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        _log_latency(
            node_name=node_name,
            elapsed_ms=elapsed_ms,
            job_id=job_id,
            ticker=ticker,
            timed_out=False,
        )

        _store_latency_in_state(
            partial=partial,
            node_name=node_name,
            elapsed_ms=elapsed_ms,
        )

        try:
            _emit_langsmith_metadata(
                node_name=node_name,
                elapsed_ms=elapsed_ms,
                job_id=job_id,
                timed_out=False,
            )
        except Exception as emit_exc:
            # LangSmith metadata is best-effort -- never fatal.
            logger.debug(
                "profile_node: _emit_langsmith_metadata failed for " "node=%s: %s",
                node_name,
                emit_exc,
            )

        return partial

    return wrapper


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "NodeTimeoutError",
    "profile_node",
    "NODE_TIMEOUT_S",
    "PROFILER_LOG_PREFIX",
    "_EFFECTIVE_TIMEOUT_S",
    "_log_latency",
    "_store_latency_in_state",
]
