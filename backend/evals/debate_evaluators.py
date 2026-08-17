# backend/evals/debate_evaluators.py
"""
AIRP -- Debate Quality LangSmith Evaluators (T-070)

Implements the "Debate quality" eval designed in
docs/EVAL_FRAMEWORK_DESIGN.md §3.3, grading a post-debate
InvestmentState snapshot (a ContrarianReport-shaped dict, a
debate_rounds[] transcript, and an InvestmentDecision-shaped dict)
against T-070's literal acceptance criteria:

  1. Contrarian always disagrees   -- counter_arguments has >=3 entries
                                       AND bear_conviction >= 1 (never an
                                       empty, rubber-stamp report)
  2. Multi-agent engagement        -- at least one debate round has
                                       genuine (non-"no position")
                                       responses from >=2 agents
  3. Novelty (not repetition)      -- no two entries across
                                       counter_arguments + overlooked_risks
                                       are near-duplicate strings
  4. PM references debate content  -- InvestmentDecision.contrarian_response
                                       is non-empty and is NOT a verbatim
                                       substring of
                                       ContrarianReport.strongest_argument
                                       (i.e. it engages with, not just
                                       echoes, the argument)

Grading scale: all-or-nothing per snapshot -- this is a structural "did
the debate actually happen and did the PM engage with it" check, not a
graded quality score, matching EVAL_FRAMEWORK_DESIGN.md §3.3's rubric
exactly ("All-or-nothing pass/fail per run").

Novelty threshold (resolves EVAL_FRAMEWORK_DESIGN.md §7's open question)
--------------------------------------------------------------------------
Near-duplicate detection uses Jaccard similarity over lowercased,
whitespace-tokenised word sets, with a threshold of 0.6 (60% word
overlap). This was chosen over a sentence-transformers embedding-
similarity approach for three reasons: (1) zero new dependencies -- this
matches sentiment_analyst.py's own precedent of avoiding heavy NLP
dependencies for deterministic checks; (2) no model-loading cost in CI,
keeping this eval as fast and dependency-free as T-068/T-069's; (3) it is
fully deterministic and trivially explainable in a PR review ("these two
sentences share 65% of their words") in a way a cosine-similarity score
from an embedding model is not. The 0.6 threshold was picked so that two
counter-arguments discussing the same *topic* in different words (the
common case -- e.g. two arguments both mentioning "margin" or "valuation"
in an otherwise distinct sentence) do NOT trip it, while two arguments
that are trivial rewordings of each other DO. Verified empirically against
this eval's own 5-snapshot dataset: the highest pairwise similarity across
all 5 snapshots' counter_arguments/overlooked_risks is ~0.11, comfortably
below 0.6.

Never-raises contract
----------------------
Every function in this module follows the AIRP-wide "agents/evaluators
never raise" convention -- a malformed or missing field is graded as a
fail with an explanatory comment, never allowed to crash the whole
experiment.

Public interface
-----------------
    DebateGrade                    -- TypedDict: one snapshot's grading result
    NOVELTY_SIMILARITY_THRESHOLD   -- float -- the 0.6 threshold documented above
    jaccard_similarity(...)        -- pure: word-overlap similarity of two strings
    has_near_duplicate_pair(...)   -- pure: any pair of strings too similar?
    grade_debate_snapshot(...)     -- pure: full 4-check rubric for one snapshot
    compute_pass_rate(...)         -- pure: grades -> (passed, total)
    meets_debate_quality_target(...) -- pure: (passed, total) -> bool (all-or-nothing)
    debate_eval_target(...)        -- LangSmith target function (deterministic)
    contrarian_disagrees_evaluator(...) -- LangSmith evaluator (run, example) -> dict
    multi_agent_engagement_evaluator(...) -- LangSmith evaluator (run, example) -> dict
    novelty_evaluator(...)              -- LangSmith evaluator (run, example) -> dict
    pm_engages_with_debate_evaluator(...) -- LangSmith evaluator (run, example) -> dict
"""

import logging
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONTRARIAN_MIN_COUNTER_ARGUMENTS = 3
NOVELTY_SIMILARITY_THRESHOLD = 0.6
_NO_POSITION_MARKER = "no position"

# ---------------------------------------------------------------------------
# Grading result shape
# ---------------------------------------------------------------------------


class DebateGrade(TypedDict):
    """Full grading result for one post-debate snapshot."""

    name: str
    contrarian_disagrees_pass: bool
    multi_agent_engagement_pass: bool
    novelty_pass: bool
    pm_engages_with_debate_pass: bool
    overall_pass: bool
    comment: str


# ---------------------------------------------------------------------------
# Pure grading logic
# ---------------------------------------------------------------------------


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """
    Return the Jaccard similarity of two strings' lowercased word sets.

    Returns 0.0 when either string tokenises to an empty word set,
    rather than raising a division-by-zero error.

    Args:
        text_a: First string.
        text_b: Second string.

    Returns:
        float in [0.0, 1.0] -- fraction of the union of words shared
        between the two strings.
    """
    tokens_a = set(text_a.lower().split())
    tokens_b = set(text_b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def has_near_duplicate_pair(
    texts: list[str],
    threshold: float = NOVELTY_SIMILARITY_THRESHOLD,
) -> tuple[bool, tuple[str, str] | None]:
    """
    Check whether any two strings in ``texts`` are near-duplicates.

    Args:
        texts: List of strings to check pairwise.
        threshold: Jaccard similarity at or above which two strings are
            considered near-duplicates. Defaults to
            NOVELTY_SIMILARITY_THRESHOLD.

    Returns:
        (True, (text_a, text_b)) for the first near-duplicate pair found,
        or (False, None) when no pair meets the threshold.
    """
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if jaccard_similarity(texts[i], texts[j]) >= threshold:
                return True, (texts[i], texts[j])
    return False, None


def _round_has_multi_agent_engagement(round_entry: dict[str, Any]) -> bool:
    """
    True when a single debate round has genuine responses from >=2 agents.

    "Genuine" excludes the deterministic "has no position this round
    (data unavailable)" filler text debate_loop_node writes for an agent
    that hasn't run yet (e.g. Risk Officer on round 1) -- that filler
    text is a real, expected structural state, not an engaged response,
    and must not count toward multi-agent engagement.
    """
    responses = round_entry.get("agent_responses")
    if not isinstance(responses, dict):
        return False
    substantive = [
        text
        for text in responses.values()
        if isinstance(text, str)
        and text.strip()
        and _NO_POSITION_MARKER not in text.lower()
    ]
    return len(substantive) >= 2


def grade_debate_snapshot(
    name: str,
    contrarian: dict[str, Any],
    debate_rounds: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    decision: dict[str, Any],
) -> DebateGrade:
    """
    Grade one post-debate snapshot against T-070's four-check rubric.

    Never raises -- always returns a DebateGrade, treating missing or
    malformed fields as a fail on the relevant check rather than
    crashing.

    Args:
        name: Human-readable identifier for this snapshot (for reporting).
        contrarian: ContrarianReport-shaped dict.
        debate_rounds: Sequence of DebateRound-shaped dicts.
        decision: InvestmentDecision-shaped dict.

    Returns:
        DebateGrade with all four booleans and a comment explaining any
        failure.
    """
    counter_arguments = contrarian.get("counter_arguments")
    counter_arguments = counter_arguments if isinstance(counter_arguments, list) else []

    overlooked_risks = contrarian.get("overlooked_risks")
    overlooked_risks = overlooked_risks if isinstance(overlooked_risks, list) else []

    raw_conviction = contrarian.get("bear_conviction", 0)
    bear_conviction = raw_conviction if isinstance(raw_conviction, int) else 0

    strongest_argument = contrarian.get("strongest_argument")
    strongest_argument = (
        strongest_argument if isinstance(strongest_argument, str) else ""
    )

    # --- Check 1: Contrarian always disagrees --------------------------
    contrarian_disagrees_pass = (
        len(counter_arguments) >= CONTRARIAN_MIN_COUNTER_ARGUMENTS
        and bear_conviction >= 1
    )

    # --- Check 2: Multi-agent engagement --------------------------------
    rounds_list = list(debate_rounds) if debate_rounds else []
    multi_agent_engagement_pass = any(
        _round_has_multi_agent_engagement(r) for r in rounds_list if isinstance(r, dict)
    )

    # --- Check 3: Novelty (not repetition) ------------------------------
    all_claims = [
        c
        for c in (list(counter_arguments) + list(overlooked_risks))
        if isinstance(c, str)
    ]
    has_dup, dup_pair = has_near_duplicate_pair(all_claims)
    novelty_pass = not has_dup

    # --- Check 4: PM references debate content --------------------------
    raw_response = decision.get("contrarian_response")
    contrarian_response = raw_response.strip() if isinstance(raw_response, str) else ""
    stripped_strongest = strongest_argument.strip()
    pm_engages_with_debate_pass = bool(contrarian_response) and (
        not stripped_strongest
        or stripped_strongest.lower() not in contrarian_response.lower()
    )

    overall_pass = (
        contrarian_disagrees_pass
        and multi_agent_engagement_pass
        and novelty_pass
        and pm_engages_with_debate_pass
    )

    comment_parts: list[str] = []
    if not contrarian_disagrees_pass:
        comment_parts.append(
            f"only {len(counter_arguments)} counter_arguments "
            f"(need >={CONTRARIAN_MIN_COUNTER_ARGUMENTS}) or "
            f"bear_conviction={bear_conviction} < 1"
        )
    if not multi_agent_engagement_pass:
        comment_parts.append(
            "no debate round has genuine (non-'no position') responses "
            "from >=2 agents"
        )
    if not novelty_pass and dup_pair is not None:
        comment_parts.append(
            f"near-duplicate claims found (Jaccard >= "
            f"{NOVELTY_SIMILARITY_THRESHOLD}): {dup_pair[0]!r} / {dup_pair[1]!r}"
        )
    if not pm_engages_with_debate_pass:
        comment_parts.append(
            "contrarian_response is empty or verbatim-echoes "
            "strongest_argument instead of engaging with it"
        )
    comment = "; ".join(comment_parts) if comment_parts else "pass"

    return {
        "name": name,
        "contrarian_disagrees_pass": contrarian_disagrees_pass,
        "multi_agent_engagement_pass": multi_agent_engagement_pass,
        "novelty_pass": novelty_pass,
        "pm_engages_with_debate_pass": pm_engages_with_debate_pass,
        "overall_pass": overall_pass,
        "comment": comment,
    }


def compute_pass_rate(grades: list[DebateGrade]) -> tuple[int, int]:
    """Return (number of snapshots that passed every check, total)."""
    passed = sum(1 for g in grades if g["overall_pass"])
    return passed, len(grades)


def meets_debate_quality_target(passed: int, total: int) -> bool:
    """
    Return True only when every snapshot passed every check.

    All-or-nothing, matching EVAL_FRAMEWORK_DESIGN.md §3.3's rubric:
    "All-or-nothing pass/fail per run -- this is a structural 'did the
    debate actually happen' check, not a graded quality score." An empty
    dataset does not vacuously pass.
    """
    if total == 0:
        return False
    return passed == total


# ---------------------------------------------------------------------------
# LangSmith target function -- fully deterministic, no network/LLM needed
# ---------------------------------------------------------------------------


def debate_eval_target(inputs: dict[str, Any]) -> dict[str, Any]:
    """
    LangSmith target function for the debate-quality eval experiment.

    Grading here operates entirely on already-produced state (a
    ContrarianReport / debate_rounds / InvestmentDecision snapshot) --
    there is no agent call to make. This target function's only job is
    to shape LangSmith's (inputs, outputs) contract: it passes the
    snapshot straight through to grade_debate_snapshot and returns the
    grade, which the LangSmith evaluator functions below then inspect.

    Never raises: a malformed inputs dict is graded as a fail via empty
    defaults rather than propagating an exception.

    Args:
        inputs: Dict with "name", "contrarian", "debate_rounds",
            "decision" keys (matches a LangSmith dataset example's
            ``inputs`` field, built from DEBATE_EVAL_DATASET).

    Returns:
        dict -- the DebateGrade for this snapshot.
    """
    try:
        name = str(inputs.get("name", "unknown"))
        contrarian = inputs.get("contrarian")
        contrarian = contrarian if isinstance(contrarian, dict) else {}
        debate_rounds = inputs.get("debate_rounds")
        debate_rounds = (
            debate_rounds if isinstance(debate_rounds, (list, tuple)) else []
        )
        decision = inputs.get("decision")
        decision = decision if isinstance(decision, dict) else {}

        grade: dict[str, Any] = dict(
            grade_debate_snapshot(
                name=name,
                contrarian=contrarian,
                debate_rounds=debate_rounds,
                decision=decision,
            )
        )
        return grade
    except Exception as exc:  # pragma: no cover -- defensive only
        logger.exception("debate_eval_target failed for inputs=%r", inputs)
        return {
            "name": str(inputs.get("name", "unknown")),
            "contrarian_disagrees_pass": False,
            "multi_agent_engagement_pass": False,
            "novelty_pass": False,
            "pm_engages_with_debate_pass": False,
            "overall_pass": False,
            "comment": f"eval target crashed: {exc}",
        }


# ---------------------------------------------------------------------------
# LangSmith evaluator functions -- (run, example) -> result dict
# ---------------------------------------------------------------------------
#
# Typed as Any -- langsmith is in pyproject.toml's mypy
# ignore_missing_imports override list, so accepting Any directly avoids
# an unused/misleading import of its concrete Run/Example types.


def _extract_grade_from_run(run: Any) -> dict[str, Any]:
    """Pull the DebateGrade dict out of a LangSmith Run's outputs."""
    outputs = getattr(run, "outputs", None)
    return outputs if isinstance(outputs, dict) else {}


def contrarian_disagrees_evaluator(run: Any, example: Any) -> dict[str, Any]:
    """LangSmith evaluator, metric key "contrarian_disagrees"."""
    grade = _extract_grade_from_run(run)
    passed = bool(grade.get("contrarian_disagrees_pass", False))
    return {
        "key": "contrarian_disagrees",
        "score": 1 if passed else 0,
        "comment": str(grade.get("comment", "no grade produced")),
    }


def multi_agent_engagement_evaluator(run: Any, example: Any) -> dict[str, Any]:
    """LangSmith evaluator, metric key "multi_agent_engagement"."""
    grade = _extract_grade_from_run(run)
    passed = bool(grade.get("multi_agent_engagement_pass", False))
    return {
        "key": "multi_agent_engagement",
        "score": 1 if passed else 0,
        "comment": str(grade.get("comment", "no grade produced")),
    }


def novelty_evaluator(run: Any, example: Any) -> dict[str, Any]:
    """LangSmith evaluator, metric key "novelty"."""
    grade = _extract_grade_from_run(run)
    passed = bool(grade.get("novelty_pass", False))
    return {
        "key": "novelty",
        "score": 1 if passed else 0,
        "comment": str(grade.get("comment", "no grade produced")),
    }


def pm_engages_with_debate_evaluator(run: Any, example: Any) -> dict[str, Any]:
    """LangSmith evaluator, metric key "pm_engages_with_debate"."""
    grade = _extract_grade_from_run(run)
    passed = bool(grade.get("pm_engages_with_debate_pass", False))
    return {
        "key": "pm_engages_with_debate",
        "score": 1 if passed else 0,
        "comment": str(grade.get("comment", "no grade produced")),
    }


__all__ = [
    "DebateGrade",
    "CONTRARIAN_MIN_COUNTER_ARGUMENTS",
    "NOVELTY_SIMILARITY_THRESHOLD",
    "jaccard_similarity",
    "has_near_duplicate_pair",
    "grade_debate_snapshot",
    "compute_pass_rate",
    "meets_debate_quality_target",
    "debate_eval_target",
    "contrarian_disagrees_evaluator",
    "multi_agent_engagement_evaluator",
    "novelty_evaluator",
    "pm_engages_with_debate_evaluator",
]
