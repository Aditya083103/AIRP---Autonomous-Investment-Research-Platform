# backend/evals/fundamental_evaluators.py
"""
AIRP -- Fundamental Analyst LangSmith Evaluators (T-068)

Implements the "Fundamental accuracy" eval designed in
docs/EVAL_FRAMEWORK_DESIGN.md §3.1: grades ``FundamentalAnalysis.score``
against a fixed ground-truth bucket (see fundamental_eval_dataset.py) for
5 companies, following the exact rubric that design doc lays out:

  1. Directional agreement  -- score falls in the right quality bucket
  2. Honest abstention      -- the thin-data example returns score=None
                                and data_quality='insufficient'
  3. Schema validity        -- output parses with no ``error`` set
                                (for the 4 non-abstention examples)

Grading scale: binary pass/fail per example, aggregated as accuracy % --
matches T-068's acceptance criterion (accuracy >70% vs known analyst
consensus).

Two layers, deliberately kept separate (mirrors EVAL_FRAMEWORK_DESIGN.md
§4's CI-scoping guidance):

  * The GRADING LOGIC in this module (``bucket_matches``,
    ``grade_fundamental_output``, ``compute_accuracy``) is pure, has no
    network/LLM dependency, and IS covered by CI
    (backend/tests/unit/test_fundamental_evaluators.py runs it against
    synthetic mock outputs).
  * The REAL evaluation run -- calling the live agent against real market
    data and a real LLM -- happens only in ``scripts/run_eval_fundamental
    .py``, which is a manual script, NOT part of the pytest/CI gate (same
    reasoning already established for scripts/manual_qa_chat_*.py).

Never-raises contract
----------------------
Every function in this module follows the AIRP-wide "agents/evaluators
never raise" convention: ``grade_fundamental_output`` and the LangSmith
evaluator wrappers built on top of it always return a result dict, even
when the run output is malformed -- a malformed run is graded as a fail
with an explanatory comment, never allowed to crash the whole experiment.

Public interface
-----------------
    FundamentalGrade            -- TypedDict: one example's grading result
    bucket_matches(...)         -- pure: does a score fall in an expected bucket
    grade_fundamental_output(...) -- pure: full per-example grading (the 3 checks)
    compute_accuracy(...)       -- pure: aggregate pass/fail list -> accuracy %
    meets_target(...)           -- pure: accuracy % -> bool vs the >70% target
    fundamental_eval_target(...) -- LangSmith target function (calls the real agent)
    directional_accuracy_evaluator(...) -- LangSmith evaluator (run, example) -> dict
    honest_abstention_evaluator(...)    -- LangSmith evaluator (run, example) -> dict
    schema_validity_evaluator(...)      -- LangSmith evaluator (run, example) -> dict
"""

import logging
from typing import Any, TypedDict

from backend.agents.fundamental_analyst import _run_fundamental_analysis_core

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants -- bucket score ranges + accuracy target
# ---------------------------------------------------------------------------

# Nominal score range for each non-abstention bucket, on FundamentalAnalysis
# .score's 1-10 scale. Ranges deliberately overlap by BUCKET_TOLERANCE points
# at their shared boundary (e.g. neutral's upper bound 6 and strong's lower
# bound 7, both widened by 1) so a score of exactly 6 or 7 -- a genuine
# borderline call -- is not penalised for landing one point off a human
# rater's own bucket boundary. See EVAL_FRAMEWORK_DESIGN.md §3.1's rubric
# row: "within 1 point of the bucket boundary".
_BUCKET_RANGES: dict[str, tuple[int, int]] = {
    "strong": (7, 10),
    "neutral": (4, 6),
    "weak": (1, 3),
}
BUCKET_TOLERANCE = 1

# T-068's own acceptance criterion.
ACCURACY_TARGET_PCT = 70.0


# ---------------------------------------------------------------------------
# Grading result shape
# ---------------------------------------------------------------------------


class FundamentalGrade(TypedDict):
    """Full grading result for one dataset example."""

    ticker: str
    expected_bucket: str
    actual_score: int | None
    actual_data_quality: str
    directional_pass: bool
    abstention_pass: bool
    schema_pass: bool
    overall_pass: bool
    comment: str


# ---------------------------------------------------------------------------
# Pure grading logic (CI-covered, no I/O)
# ---------------------------------------------------------------------------


def bucket_matches(score: int | None, expected_bucket: str) -> bool:
    """
    Return True when ``score`` falls inside ``expected_bucket``'s range,
    widened by ``BUCKET_TOLERANCE`` points on each side.

    ``expected_bucket == "insufficient"`` always returns False here --
    that case is graded by ``_abstention_pass``, not a numeric range,
    since "insufficient" has no score range to fall inside.

    Args:
        score: The agent's ``FundamentalAnalysis.score`` (1-10 or None).
        expected_bucket: One of "strong" / "neutral" / "weak" /
            "insufficient".

    Returns:
        bool -- True when the score is a directional match.
    """
    if score is None:
        return False
    bucket_range = _BUCKET_RANGES.get(expected_bucket)
    if bucket_range is None:
        return False
    low, high = bucket_range
    return (low - BUCKET_TOLERANCE) <= score <= (high + BUCKET_TOLERANCE)


def _abstention_pass(
    expected_bucket: str,
    score: int | None,
    data_quality: str,
) -> bool:
    """
    Grade the "honest abstention" check.

    Only meaningful for the one ``expected_bucket == "insufficient"``
    example -- returns True there only when the agent actually reported
    ``score=None`` and ``data_quality="insufficient"`` (never a
    confidently-wrong number). For every other example this check is not
    applicable and is reported as passing (there is nothing to abstain
    from), so it never drags down a non-abstention example's
    ``overall_pass``.
    """
    if expected_bucket != "insufficient":
        return True
    return score is None and data_quality == "insufficient"


def grade_fundamental_output(
    ticker: str,
    expected_bucket: str,
    actual_score: int | None,
    actual_data_quality: str,
    actual_error: str | None,
) -> FundamentalGrade:
    """
    Grade one agent output against its ground-truth bucket.

    Applies all three rubric checks from EVAL_FRAMEWORK_DESIGN.md §3.1:
    directional agreement, honest abstention, and schema validity.
    Schema validity is graded here as "no ``error`` set" -- Pydantic
    parsing itself is enforced upstream by ``FundamentalAnalysis``'s own
    validators (an unparseable output never reaches this function as a
    valid ``FundamentalAnalysis`` instance in the first place).

    Never raises -- always returns a ``FundamentalGrade``, even for
    surprising inputs (e.g. an out-of-range score), by grading the
    surprising case as a fail rather than crashing.

    Args:
        ticker: The company ticker under evaluation.
        expected_bucket: Ground-truth bucket from the dataset.
        actual_score: The agent's returned score (1-10 or None).
        actual_data_quality: The agent's returned data_quality string.
        actual_error: The agent's returned error string, if any.

    Returns:
        FundamentalGrade with all four booleans and a human-readable
        comment explaining any failure.
    """
    is_abstention_case = expected_bucket == "insufficient"

    directional_pass = (
        True if is_abstention_case else bucket_matches(actual_score, expected_bucket)
    )
    abstention_pass = _abstention_pass(
        expected_bucket, actual_score, actual_data_quality
    )
    schema_pass = True if is_abstention_case else actual_error is None

    overall_pass = directional_pass and abstention_pass and schema_pass

    comment_parts: list[str] = []
    if not directional_pass:
        comment_parts.append(
            f"score={actual_score!r} not in expected '{expected_bucket}' bucket "
            f"(±{BUCKET_TOLERANCE})"
        )
    if not abstention_pass:
        comment_parts.append(
            f"expected honest abstention (score=None, "
            f"data_quality='insufficient') but got "
            f"score={actual_score!r}, data_quality={actual_data_quality!r}"
        )
    if not schema_pass:
        comment_parts.append(f"unexpected error set: {actual_error!r}")
    comment = "; ".join(comment_parts) if comment_parts else "pass"

    return {
        "ticker": ticker,
        "expected_bucket": expected_bucket,
        "actual_score": actual_score,
        "actual_data_quality": actual_data_quality,
        "directional_pass": directional_pass,
        "abstention_pass": abstention_pass,
        "schema_pass": schema_pass,
        "overall_pass": overall_pass,
        "comment": comment,
    }


def compute_accuracy(grades: list[FundamentalGrade]) -> float:
    """
    Aggregate a list of per-example grades into an overall accuracy %.

    Returns 0.0 for an empty list rather than raising a
    division-by-zero error -- matches the AIRP-wide never-raises
    convention for aggregation functions (mirrors
    accuracy_tracker.get_accuracy_summary()'s "never a fabricated
    number" caution, though here an empty eval run is itself the
    anomaly worth surfacing as 0%, not None, since T-068's acceptance
    criterion is a plain numeric threshold check).

    Args:
        grades: Per-example grading results.

    Returns:
        float -- percentage (0.0-100.0) of examples with overall_pass=True.
    """
    if not grades:
        return 0.0
    passed = sum(1 for g in grades if g["overall_pass"])
    return round((passed / len(grades)) * 100.0, 2)


def meets_target(accuracy_pct: float) -> bool:
    """Return True when ``accuracy_pct`` meets T-068's >70% target."""
    return accuracy_pct > ACCURACY_TARGET_PCT


# ---------------------------------------------------------------------------
# LangSmith target function -- calls the REAL agent (not used in CI)
# ---------------------------------------------------------------------------


def fundamental_eval_target(inputs: dict[str, Any]) -> dict[str, Any]:
    """
    LangSmith target function for the Fundamental Analyst eval experiment.

    Calls the real ``_run_fundamental_analysis_core`` -- real yFinance /
    Alpha Vantage fetches, real LLM call -- exactly the same core function
    the production LangGraph node (``run_fundamental_analysis``) calls.
    Intentionally bypasses the ``@traced_agent``-wrapped node function so
    ``langsmith.evaluate()`` owns the top-level trace/run for this
    experiment rather than nesting a second, redundant trace inside it.

    Never raises: on any failure returns a dict with ``error`` set instead
    of propagating, so a single bad example does not abort the whole
    LangSmith experiment run.

    Args:
        inputs: Dict with "company_name" and "ticker" keys (matches a
            LangSmith dataset example's ``inputs`` field, built from
            ``FUNDAMENTAL_EVAL_DATASET``).

    Returns:
        dict -- ``FundamentalAnalysis.model_dump()`` on success, or a
        minimal error dict on failure.
    """
    company_name = str(inputs.get("company_name", "Unknown Company"))
    ticker = str(inputs.get("ticker", ""))
    try:
        result = _run_fundamental_analysis_core(
            analysis_id="eval-fundamental",
            company_name=company_name,
            ticker=ticker,
        )
        return result.model_dump()
    except Exception as exc:  # pragma: no cover -- exercised only in manual runs
        logger.exception("fundamental_eval_target failed for ticker=%s", ticker)
        return {
            "score": None,
            "data_quality": "insufficient",
            "error": f"eval target crashed: {exc}",
        }


# ---------------------------------------------------------------------------
# LangSmith evaluator functions -- (run, example) -> result dict
# ---------------------------------------------------------------------------
#
# Signatures follow the langsmith.evaluate() evaluator contract: each
# receives the experiment's Run (whose .outputs is whatever
# fundamental_eval_target returned) and the source Example (whose
# .outputs is the dataset's reference_outputs). Typed as Any -- langsmith
# is in pyproject.toml's mypy ignore_missing_imports override list, so
# importing its concrete Run/Example types would still resolve to Any at
# every attribute access; accepting Any directly here is equivalent and
# avoids an unused/misleading import.


def _extract_run_fields(run: Any) -> tuple[int | None, str, str | None]:
    """
    Pull (score, data_quality, error) out of a LangSmith Run's outputs.

    Defensive against a malformed/missing outputs dict, or fields of an
    unexpected type -- returns fail-safe defaults rather than raising or
    propagating a wrongly-typed value, consistent with this module's
    never-raises contract.
    """
    outputs = getattr(run, "outputs", None)
    if not isinstance(outputs, dict):
        return None, "insufficient", "run.outputs missing or not a dict"

    raw_score = outputs.get("score")
    score: int | None = raw_score if isinstance(raw_score, int) else None

    raw_quality = outputs.get("data_quality", "insufficient")
    data_quality: str = raw_quality if isinstance(raw_quality, str) else "insufficient"

    raw_error = outputs.get("error")
    error: str | None = raw_error if isinstance(raw_error, str) else None

    return score, data_quality, error


def _extract_expected_bucket(example: Any) -> str:
    """Pull the expected bucket out of a LangSmith Example's outputs."""
    outputs = getattr(example, "outputs", None)
    if not isinstance(outputs, dict):
        return "insufficient"
    raw_bucket = outputs.get("expected_bucket", "insufficient")
    return raw_bucket if isinstance(raw_bucket, str) else "insufficient"


def _grade_run_against_example(run: Any, example: Any) -> FundamentalGrade:
    """Shared plumbing: extract fields from (run, example) and grade them."""
    score, data_quality, error = _extract_run_fields(run)
    expected_bucket = _extract_expected_bucket(example)
    ticker = str(getattr(run, "inputs", {}).get("ticker", "unknown"))
    return grade_fundamental_output(
        ticker=ticker,
        expected_bucket=expected_bucket,
        actual_score=score,
        actual_data_quality=data_quality,
        actual_error=error,
    )


def directional_accuracy_evaluator(run: Any, example: Any) -> dict[str, Any]:
    """
    LangSmith evaluator: directional bucket agreement (rubric check 1).

    Registered under the LangSmith metric key "directional_accuracy".
    """
    grade = _grade_run_against_example(run, example)
    return {
        "key": "directional_accuracy",
        "score": 1 if grade["directional_pass"] else 0,
        "comment": grade["comment"],
    }


def honest_abstention_evaluator(run: Any, example: Any) -> dict[str, Any]:
    """
    LangSmith evaluator: honest-abstention check (rubric check 2).

    Registered under the LangSmith metric key "honest_abstention". Scores
    1 for every non-abstention example (nothing to abstain from) so this
    metric only meaningfully penalises the one insufficient-data row.
    """
    grade = _grade_run_against_example(run, example)
    return {
        "key": "honest_abstention",
        "score": 1 if grade["abstention_pass"] else 0,
        "comment": grade["comment"],
    }


def schema_validity_evaluator(run: Any, example: Any) -> dict[str, Any]:
    """
    LangSmith evaluator: schema validity check (rubric check 3).

    Registered under the LangSmith metric key "schema_validity".
    """
    grade = _grade_run_against_example(run, example)
    return {
        "key": "schema_validity",
        "score": 1 if grade["schema_pass"] else 0,
        "comment": grade["comment"],
    }


__all__ = [
    "FundamentalGrade",
    "ACCURACY_TARGET_PCT",
    "BUCKET_TOLERANCE",
    "bucket_matches",
    "grade_fundamental_output",
    "compute_accuracy",
    "meets_target",
    "fundamental_eval_target",
    "directional_accuracy_evaluator",
    "honest_abstention_evaluator",
    "schema_validity_evaluator",
]
