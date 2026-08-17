# backend/evals/sentiment_evaluators.py
"""
AIRP -- News Sentiment Agent LangSmith Evaluators (T-069)

Implements the "Sentiment direction" eval designed in
docs/EVAL_FRAMEWORK_DESIGN.md §3.2: grades sentiment direction against 10
known-direction news sets, and grades red-flag detection against 3 known
scandal cases, following that design doc's rubric exactly:

  1. Directional accuracy  -- sentiment_label is on the correct side of
                               neutral (positive sets score > 0, negative
                               sets score < 0) for >80% of the 10 sets
  2. Red-flag detection    -- red_flag_count >= 1 for all 3 scandal cases
  3. No false alarms       -- the 10 direction sets never spuriously
                               populate red_flags

Grading scale: T-069's acceptance criteria verbatim -- directional
accuracy >80% on 10 test news sets; red-flag detection verified (3-of-3,
all-or-nothing) for the 3 scandal cases.

A key architectural difference from the Fundamental Analyst eval (T-068):
sentiment_score, sentiment_label, and the keyword-detected portion of
red_flags are ALL produced by pure, deterministic functions in
backend/agents/sentiment_analyst.py -- _score_article, _aggregate_scores,
_label_from_score, _detect_red_flags -- with NO network call and NO LLM
call. This module imports and reuses those exact functions (never
reimplements the scoring logic) so the eval can never silently drift from
the real agent's behaviour. One consequence: this eval, unlike T-068's,
can be asserted directly inside a normal CI-covered pytest test against
the FULL real dataset, not just against synthetic mock outputs -- see
TestFullDatasetMeetsTargets in
backend/tests/unit/test_sentiment_evaluators.py.

The LLM-synthesised fields (top_positive_headlines, dominant_topics,
summary, and any additional LLM-suggested red_flags) are explicitly OUT
OF SCOPE for this eval -- T-069's acceptance criteria are about
sentiment DIRECTION and red-flag DETECTION, both of which are fully
determined before the LLM is ever called.

Never-raises contract
----------------------
Every function in this module follows the AIRP-wide "agents/evaluators
never raise" convention -- grading functions and LangSmith evaluator
wrappers always return a result, even for a malformed run, grading it as
a fail with an explanatory comment rather than crashing the experiment.

Public interface
-----------------
    DirectionGrade                  -- TypedDict: one direction example's result
    ScandalGrade                    -- TypedDict: one scandal example's result
    DIRECTION_ACCURACY_TARGET_PCT   -- float -- T-069's >80% target
    score_news_set(...)             -- pure: reuses the real agent's own scoring
    direction_matches(...)          -- pure: score/label vs expected direction
    grade_direction_example(...)    -- pure: full per-example direction grading
    grade_scandal_example(...)      -- pure: full per-example scandal grading
    compute_direction_accuracy(...) -- pure: direction grades -> accuracy %
    meets_direction_target(...)     -- pure: accuracy % -> bool vs >80% target
    compute_scandal_detection(...)  -- pure: scandal grades -> (passed, total)
    meets_scandal_target(...)       -- pure: (passed, total) -> bool (3-of-3)
    sentiment_eval_target(...)      -- LangSmith target function (deterministic)
    direction_accuracy_evaluator(...) -- LangSmith evaluator (run, example) -> dict
    no_false_alarm_evaluator(...)     -- LangSmith evaluator (run, example) -> dict
    red_flag_detection_evaluator(...) -- LangSmith evaluator (run, example) -> dict
"""

import logging
from typing import Any, TypedDict

from backend.agents.sentiment_analyst import (
    _aggregate_scores,
    _detect_red_flags,
    _label_from_score,
    _score_article,
)
from backend.evals.sentiment_eval_dataset import ArticleInput

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants -- T-069's own acceptance criteria
# ---------------------------------------------------------------------------

DIRECTION_ACCURACY_TARGET_PCT = 80.0
SCANDAL_DETECTION_REQUIRED = "all"  # all-or-nothing, see meets_scandal_target


# ---------------------------------------------------------------------------
# Grading result shapes
# ---------------------------------------------------------------------------


class DirectionGrade(TypedDict):
    """Full grading result for one directional test news set."""

    name: str
    expected_direction: str
    actual_score: float
    actual_label: str
    actual_red_flags: list[str]
    direction_pass: bool
    no_false_alarm_pass: bool
    overall_pass: bool
    comment: str


class ScandalGrade(TypedDict):
    """Full grading result for one known-scandal test case."""

    name: str
    actual_red_flags: list[str]
    red_flag_count: int
    matched_expected_keywords: tuple[str, ...]
    overall_pass: bool
    comment: str


# ---------------------------------------------------------------------------
# Pure grading logic -- reuses the REAL agent's own scoring functions
# ---------------------------------------------------------------------------


def score_news_set(
    articles: tuple[ArticleInput, ...],
) -> tuple[float, str, list[str]]:
    """
    Score a set of synthetic articles using the real agent's own pipeline.

    Deliberately calls the exact same pure functions
    (backend.agents.sentiment_analyst._score_article /
    _aggregate_scores / _label_from_score / _detect_red_flags) that
    ``_run_sentiment_analysis_core`` calls in production -- this eval
    never reimplements the scoring logic, so it can't silently drift
    from the real agent's behaviour.

    Args:
        articles: Tuple of ArticleInput dicts (title + description).

    Returns:
        (aggregate_score, sentiment_label, red_flags) -- exactly the
        deterministic subset of SentimentAnalysis's fields this eval
        grades (the LLM-synthesised fields are out of scope, see this
        module's docstring).
    """
    per_article_scores = [
        _score_article(article["title"], article["description"]) for article in articles
    ]
    article_texts = [
        f"{article['title']} {article['description']}" for article in articles
    ]

    aggregate_score = _aggregate_scores(per_article_scores)
    label = _label_from_score(aggregate_score)
    red_flags = _detect_red_flags(article_texts)

    return aggregate_score, label, red_flags


def direction_matches(score: float, label: str, expected_direction: str) -> bool:
    """
    Return True when (score, label) agree with ``expected_direction``.

    Matches EVAL_FRAMEWORK_DESIGN.md §3.2's rubric exactly:
      * "positive"  -> ``score > 0``
      * "negative"  -> ``score < 0``
      * "neutral"   -> ``label == "neutral"`` -- delegates to the real
        ``_label_from_score``'s own neutral-band definition rather than
        re-deriving the -0.1/+0.1 boundary here, so this function can
        never silently drift from the agent's actual neutral band if
        that band is ever retuned.

    Args:
        score: Aggregate sentiment score from ``score_news_set``.
        label: Sentiment label from ``score_news_set``.
        expected_direction: One of "positive" / "negative" / "neutral".

    Returns:
        bool -- True when the direction matches; False for an unknown
        ``expected_direction`` value rather than raising.
    """
    if expected_direction == "positive":
        return score > 0
    if expected_direction == "negative":
        return score < 0
    if expected_direction == "neutral":
        return label == "neutral"
    return False


def grade_direction_example(
    name: str,
    expected_direction: str,
    actual_score: float,
    actual_label: str,
    actual_red_flags: list[str],
) -> DirectionGrade:
    """
    Grade one directional example's actual output against ground truth.

    Applies both rubric rows this dataset covers: directional agreement
    and "no false alarms" (none of the 10 direction sets should ever
    populate ``red_flags`` -- see EVAL_FRAMEWORK_DESIGN.md §3.2).

    Never raises -- always returns a DirectionGrade.
    """
    direction_pass = direction_matches(actual_score, actual_label, expected_direction)
    no_false_alarm_pass = len(actual_red_flags) == 0
    overall_pass = direction_pass and no_false_alarm_pass

    comment_parts: list[str] = []
    if not direction_pass:
        comment_parts.append(
            f"score={actual_score!r} label={actual_label!r} does not match "
            f"expected direction '{expected_direction}'"
        )
    if not no_false_alarm_pass:
        comment_parts.append(
            f"unexpected red_flags on a non-scandal set: {actual_red_flags!r}"
        )
    comment = "; ".join(comment_parts) if comment_parts else "pass"

    return {
        "name": name,
        "expected_direction": expected_direction,
        "actual_score": actual_score,
        "actual_label": actual_label,
        "actual_red_flags": actual_red_flags,
        "direction_pass": direction_pass,
        "no_false_alarm_pass": no_false_alarm_pass,
        "overall_pass": overall_pass,
        "comment": comment,
    }


def grade_scandal_example(
    name: str,
    expected_flag_keywords: tuple[str, ...],
    actual_red_flags: list[str],
) -> ScandalGrade:
    """
    Grade one scandal example's actual output against ground truth.

    T-069's acceptance criterion is "red_flag detection verified" --
    graded here as at least one flag detected (``red_flag_count >= 1``).
    ``matched_expected_keywords`` is additional evidence (which of the
    example's documented expected keywords actually showed up in the
    flags) surfaced for PR review, but is NOT required for
    ``overall_pass`` -- a real scandal case may trip a different but
    equally valid RED_FLAG_PHRASES entry than the ones anticipated when
    the dataset was authored, and that should still count as detection
    working correctly.

    Never raises -- always returns a ScandalGrade.
    """
    red_flag_count = len(actual_red_flags)
    joined_flags = " ".join(actual_red_flags).lower()
    matched = tuple(kw for kw in expected_flag_keywords if kw in joined_flags)

    overall_pass = red_flag_count >= 1

    comment = (
        "pass"
        if overall_pass
        else "no red flags detected on a known-scandal test case (hard fail)"
    )

    return {
        "name": name,
        "actual_red_flags": actual_red_flags,
        "red_flag_count": red_flag_count,
        "matched_expected_keywords": matched,
        "overall_pass": overall_pass,
        "comment": comment,
    }


def compute_direction_accuracy(grades: list[DirectionGrade]) -> float:
    """
    Aggregate direction grades into an overall accuracy %.

    Returns 0.0 for an empty list rather than raising, matching the
    same never-raises aggregation convention used in
    backend/evals/fundamental_evaluators.py's compute_accuracy.
    """
    if not grades:
        return 0.0
    passed = sum(1 for g in grades if g["overall_pass"])
    return round((passed / len(grades)) * 100.0, 2)


def meets_direction_target(accuracy_pct: float) -> bool:
    """Return True when ``accuracy_pct`` meets T-069's >80% target."""
    return accuracy_pct > DIRECTION_ACCURACY_TARGET_PCT


def compute_scandal_detection(grades: list[ScandalGrade]) -> tuple[int, int]:
    """Return (number of scandal cases with a detected flag, total)."""
    passed = sum(1 for g in grades if g["overall_pass"])
    return passed, len(grades)


def meets_scandal_target(passed: int, total: int) -> bool:
    """
    Return True only when every scandal case triggered a red flag.

    All-or-nothing per EVAL_FRAMEWORK_DESIGN.md §3.2: "graded separately
    as 3/3 required (all-or-nothing, since this is a safety-adjacent
    check -- a missed scandal is a worse failure mode than a missed
    sentiment nuance)." Returns False for a 0-case run rather than
    treating an empty set as vacuously passing.
    """
    if total == 0:
        return False
    return passed == total


# ---------------------------------------------------------------------------
# LangSmith target function -- fully deterministic, no network/LLM needed
# ---------------------------------------------------------------------------


def sentiment_eval_target(inputs: dict[str, Any]) -> dict[str, Any]:
    """
    LangSmith target function for the Sentiment Agent eval experiment.

    Unlike T-068's fundamental_eval_target, this makes NO network call
    and NO LLM call -- sentiment_score/sentiment_label/red_flags are all
    deterministic outputs of score_news_set(). This is still wired
    through langsmith.evaluate() (see scripts/run_eval_sentiment.py) so
    results land in the LangSmith dashboard alongside every other AIRP
    eval, per EVAL_FRAMEWORK_DESIGN.md §4's shared naming convention --
    but nothing about the grading itself depends on that being run.

    Never raises: a malformed ``inputs`` dict is graded as a fail via
    an empty article set rather than propagating an exception.

    Args:
        inputs: Dict with an "articles" key -- a list of
            {"title": str, "description": str} dicts (matches a
            LangSmith dataset example's ``inputs`` field, built from
            SENTIMENT_DIRECTION_DATASET / SENTIMENT_SCANDAL_DATASET).

    Returns:
        dict with "sentiment_score", "sentiment_label", "red_flags".
    """
    try:
        raw_articles = inputs.get("articles", [])
        articles_list: list[ArticleInput] = []
        for raw_article in raw_articles:
            if isinstance(raw_article, dict):
                articles_list.append(
                    {
                        "title": str(raw_article.get("title", "")),
                        "description": str(raw_article.get("description", "")),
                    }
                )
        articles: tuple[ArticleInput, ...] = tuple(articles_list)
        score, label, flags = score_news_set(articles)
        return {
            "sentiment_score": score,
            "sentiment_label": label,
            "red_flags": flags,
        }
    except Exception as exc:  # pragma: no cover -- defensive only
        logger.exception("sentiment_eval_target failed for inputs=%r", inputs)
        return {
            "sentiment_score": 0.0,
            "sentiment_label": "neutral",
            "red_flags": [],
            "error": f"eval target crashed: {exc}",
        }


# ---------------------------------------------------------------------------
# LangSmith evaluator functions -- (run, example) -> result dict
# ---------------------------------------------------------------------------
#
# Typed as Any -- langsmith is in pyproject.toml's mypy
# ignore_missing_imports override list, so accepting Any directly avoids
# an unused/misleading import of its concrete Run/Example types.


def _extract_target_outputs(run: Any) -> tuple[float, str, list[str]]:
    """
    Pull (score, label, red_flags) out of a LangSmith Run's outputs.

    Defensive against a malformed/missing outputs dict -- returns
    fail-safe defaults rather than raising.
    """
    outputs = getattr(run, "outputs", None)
    if not isinstance(outputs, dict):
        return 0.0, "neutral", []

    raw_score = outputs.get("sentiment_score")
    score = float(raw_score) if isinstance(raw_score, (int, float)) else 0.0

    raw_label = outputs.get("sentiment_label")
    label = raw_label if isinstance(raw_label, str) else "neutral"

    raw_flags = outputs.get("red_flags")
    flags = list(raw_flags) if isinstance(raw_flags, list) else []

    return score, label, flags


def _extract_example_fields(example: Any) -> dict[str, Any]:
    """Pull the reference outputs dict out of a LangSmith Example."""
    outputs = getattr(example, "outputs", None)
    return outputs if isinstance(outputs, dict) else {}


def _example_name(example: Any) -> str:
    fields = _extract_example_fields(example)
    raw_name = fields.get("name", "unknown")
    return raw_name if isinstance(raw_name, str) else "unknown"


def direction_accuracy_evaluator(run: Any, example: Any) -> dict[str, Any]:
    """
    LangSmith evaluator: directional agreement for one direction example.

    Registered under the LangSmith metric key "directional_accuracy".
    """
    score, label, flags = _extract_target_outputs(run)
    fields = _extract_example_fields(example)
    expected_direction = fields.get("expected_direction", "neutral")
    grade = grade_direction_example(
        name=_example_name(example),
        expected_direction=str(expected_direction),
        actual_score=score,
        actual_label=label,
        actual_red_flags=flags,
    )
    return {
        "key": "directional_accuracy",
        "score": 1 if grade["direction_pass"] else 0,
        "comment": grade["comment"],
    }


def no_false_alarm_evaluator(run: Any, example: Any) -> dict[str, Any]:
    """
    LangSmith evaluator: no spurious red flags on a direction example.

    Registered under the LangSmith metric key "no_false_alarms".
    """
    score, label, flags = _extract_target_outputs(run)
    fields = _extract_example_fields(example)
    expected_direction = fields.get("expected_direction", "neutral")
    grade = grade_direction_example(
        name=_example_name(example),
        expected_direction=str(expected_direction),
        actual_score=score,
        actual_label=label,
        actual_red_flags=flags,
    )
    return {
        "key": "no_false_alarms",
        "score": 1 if grade["no_false_alarm_pass"] else 0,
        "comment": grade["comment"],
    }


def red_flag_detection_evaluator(run: Any, example: Any) -> dict[str, Any]:
    """
    LangSmith evaluator: red-flag detection for one scandal example.

    Registered under the LangSmith metric key "red_flag_detection".
    """
    _, _, flags = _extract_target_outputs(run)
    fields = _extract_example_fields(example)
    raw_keywords = fields.get("expected_flag_keywords", ())
    expected_keywords = (
        tuple(raw_keywords) if isinstance(raw_keywords, (list, tuple)) else ()
    )
    grade = grade_scandal_example(
        name=_example_name(example),
        expected_flag_keywords=expected_keywords,
        actual_red_flags=flags,
    )
    return {
        "key": "red_flag_detection",
        "score": 1 if grade["overall_pass"] else 0,
        "comment": grade["comment"],
    }


__all__ = [
    "DirectionGrade",
    "ScandalGrade",
    "DIRECTION_ACCURACY_TARGET_PCT",
    "score_news_set",
    "direction_matches",
    "grade_direction_example",
    "grade_scandal_example",
    "compute_direction_accuracy",
    "meets_direction_target",
    "compute_scandal_detection",
    "meets_scandal_target",
    "sentiment_eval_target",
    "direction_accuracy_evaluator",
    "no_false_alarm_evaluator",
    "red_flag_detection_evaluator",
]
