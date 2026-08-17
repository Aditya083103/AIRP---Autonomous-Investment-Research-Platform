# backend/tests/unit/test_debate_evaluators.py
"""
Unit tests for T-070: Debate Quality LangSmith Eval.

Test strategy:
  1. Dataset shape            -- 5 snapshots, unique names, every snapshot
                                  schema-faithful to ContrarianReport /
                                  DebateRound / InvestmentDecision
  2. jaccard_similarity() / has_near_duplicate_pair() -- pure similarity logic
  3. grade_debate_snapshot()  -- the full 4-check rubric, including
                                  synthetic MALFORMED fixtures that prove
                                  the grading logic actually catches a
                                  violation of each individual check (not
                                  just that the real dataset happens to
                                  pass)
  4. compute_pass_rate() / meets_debate_quality_target()
  5. debate_eval_target()     -- deterministic target function, no
                                  mocking needed
  6. LangSmith evaluator wrappers -- (run, example) -> dict
  7. TestFullDatasetMeetsTargets -- runs the ENTIRE real dataset through
                                  the real grading pipeline and asserts
                                  it meets T-070's literal acceptance
                                  criteria. Possible here for the same
                                  reason it was possible for T-069:
                                  grading a debate snapshot has zero
                                  network/LLM dependency (unlike T-068).

None of these tests call a real LLM or hit the network. This entire
suite runs fully offline, deterministically, every time.
"""
from __future__ import annotations

import os

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "test")

from types import SimpleNamespace  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402

from backend.evals.debate_eval_dataset import DEBATE_EVAL_DATASET  # noqa: E402
from backend.evals.debate_evaluators import (  # noqa: E402
    CONTRARIAN_MIN_COUNTER_ARGUMENTS,
    NOVELTY_SIMILARITY_THRESHOLD,
    compute_pass_rate,
    contrarian_disagrees_evaluator,
    debate_eval_target,
    grade_debate_snapshot,
    has_near_duplicate_pair,
    jaccard_similarity,
    meets_debate_quality_target,
    multi_agent_engagement_evaluator,
    novelty_evaluator,
    pm_engages_with_debate_evaluator,
)

# ---------------------------------------------------------------------------
# 1. Dataset shape
# ---------------------------------------------------------------------------


class TestDatasetShape:
    def test_has_exactly_five_examples(self) -> None:
        assert len(DEBATE_EVAL_DATASET) == 5

    def test_names_are_unique(self) -> None:
        names = [ex["name"] for ex in DEBATE_EVAL_DATASET]
        assert len(names) == len(set(names))

    def test_every_snapshot_has_at_least_one_debate_round(self) -> None:
        for ex in DEBATE_EVAL_DATASET:
            assert len(ex["debate_rounds"]) >= 1

    def test_every_contrarian_has_required_fields(self) -> None:
        required = {
            "agent_name",
            "counter_arguments",
            "challenged_agents",
            "overlooked_risks",
            "bear_conviction",
            "strongest_argument",
            "summary",
        }
        for ex in DEBATE_EVAL_DATASET:
            assert required.issubset(ex["contrarian"].keys()), ex["name"]

    def test_every_decision_has_required_fields(self) -> None:
        required = {
            "agent_name",
            "verdict",
            "conviction_score",
            "contrarian_response",
            "debate_rounds_used",
            "agent_weights",
            "summary",
        }
        for ex in DEBATE_EVAL_DATASET:
            assert required.issubset(ex["decision"].keys()), ex["name"]

    def test_every_debate_round_has_required_fields(self) -> None:
        required = {"round_number", "agent_responses", "contrarian", "completed_at"}
        for ex in DEBATE_EVAL_DATASET:
            for r in ex["debate_rounds"]:
                assert required.issubset(r.keys()), (ex["name"], r["round_number"])

    def test_verdicts_span_buy_sell_and_hold(self) -> None:
        """
        A reliability proof about ONE outcome type isn't very convincing
        -- the dataset spans all three verdict types.
        """
        verdicts = {ex["decision"]["verdict"] for ex in DEBATE_EVAL_DATASET}
        assert verdicts == {"BUY", "SELL", "HOLD"}


# ---------------------------------------------------------------------------
# 2. jaccard_similarity() / has_near_duplicate_pair()
# ---------------------------------------------------------------------------


class TestJaccardSimilarity:
    def test_identical_strings_have_similarity_one(self) -> None:
        assert (
            jaccard_similarity("the stock is overvalued", "the stock is overvalued")
            == 1.0
        )

    def test_completely_different_strings_have_similarity_zero(self) -> None:
        assert jaccard_similarity("apple banana cherry", "dog elephant fox") == 0.0

    def test_partial_overlap_is_between_zero_and_one(self) -> None:
        sim = jaccard_similarity(
            "margins are declining due to input costs",
            "margins are improving due to pricing power",
        )
        assert 0.0 < sim < 1.0

    def test_empty_string_returns_zero_not_raises(self) -> None:
        assert jaccard_similarity("", "something here") == 0.0
        assert jaccard_similarity("something here", "") == 0.0
        assert jaccard_similarity("", "") == 0.0

    def test_case_insensitive(self) -> None:
        assert jaccard_similarity("STRONG GROWTH", "strong growth") == 1.0


class TestHasNearDuplicatePair:
    def test_no_duplicates_among_distinct_strings(self) -> None:
        texts = [
            "Revenue growth has lagged peers for years.",
            "Leadership transition adds execution risk.",
            "Technical momentum is weaker than it appears.",
        ]
        has_dup, pair = has_near_duplicate_pair(texts)
        assert has_dup is False
        assert pair is None

    def test_detects_a_near_duplicate_pair(self) -> None:
        texts = [
            "Margins are declining due to rising input costs across the board.",
            "Margins are declining due to rising input costs across the "
            "whole business.",
            "An unrelated third statement about something else entirely.",
        ]
        has_dup, pair = has_near_duplicate_pair(texts)
        assert has_dup is True
        assert pair is not None

    def test_empty_list_has_no_duplicates(self) -> None:
        has_dup, pair = has_near_duplicate_pair([])
        assert has_dup is False
        assert pair is None

    def test_single_item_has_no_duplicates(self) -> None:
        has_dup, pair = has_near_duplicate_pair(["just one claim here"])
        assert has_dup is False

    def test_custom_threshold_is_respected(self) -> None:
        texts = ["strong growth outlook", "strong growth story"]
        # 4 of 6 total words shared across the union -> similarity 0.5.
        assert jaccard_similarity(texts[0], texts[1]) == pytest.approx(0.5, abs=0.01)
        has_dup_strict, _ = has_near_duplicate_pair(texts, threshold=0.6)
        has_dup_loose, _ = has_near_duplicate_pair(texts, threshold=0.4)
        assert has_dup_strict is False
        assert has_dup_loose is True


# ---------------------------------------------------------------------------
# 3. grade_debate_snapshot() -- including synthetic MALFORMED fixtures
# ---------------------------------------------------------------------------

_GOOD_CONTRARIAN: dict[str, Any] = {
    "agent_name": "contrarian_investor",
    "counter_arguments": [
        "Revenue growth has lagged the two largest peers for years.",
        "Leadership transition adds meaningful execution risk right now.",
        "Technical momentum looks weaker than the headline trend suggests.",
    ],
    "challenged_agents": ["fundamental_analyst"],
    "overlooked_risks": [
        "Acquisition integration risk has not yet shown up in margins.",
    ],
    "bear_conviction": 5,
    "strongest_argument": "Revenue growth has lagged peers for several years running.",
    "summary": "A persistent growth-gap story, not a distress case.",
}

_GOOD_ROUNDS: list[dict[str, Any]] = [
    {
        "round_number": 1,
        "agent_responses": {
            "fundamental": (
                "Fundamental Analyst reaffirms its prior position "
                "on balance sheet strength."
            ),
            "technical": (
                "Technical Analyst acknowledges the challenge but " "holds its view."
            ),
            "sentiment": "News Sentiment Agent reaffirms its prior neutral read.",
            "macro": "Macro Economist reaffirms a stable sector outlook.",
            "risk": "Risk Officer has no position this round (data unavailable).",
        },
        "contrarian": "Revenue growth has lagged peers for several years running.",
        "completed_at": "2026-01-01T00:00:00Z",
    }
]

_GOOD_DECISION: dict[str, Any] = {
    "agent_name": "portfolio_manager",
    "verdict": "HOLD",
    "conviction_score": 5,
    "contrarian_response": (
        "The committee agrees the growth gap versus peers is real and "
        "reflects it directly in a modest conviction score, while noting "
        "balance-sheet strength provides downside protection."
    ),
    "debate_rounds_used": 1,
    "agent_weights": {"fundamental_analyst": 0.3, "contrarian_investor": 0.2},
    "summary": "HOLD -- persistent growth gap versus peers",
}


class TestGradeDebateSnapshot:
    def test_well_formed_snapshot_passes_all_checks(self) -> None:
        grade = grade_debate_snapshot(
            name="good",
            contrarian=_GOOD_CONTRARIAN,
            debate_rounds=_GOOD_ROUNDS,
            decision=_GOOD_DECISION,
        )
        assert grade["overall_pass"] is True
        assert grade["contrarian_disagrees_pass"] is True
        assert grade["multi_agent_engagement_pass"] is True
        assert grade["novelty_pass"] is True
        assert grade["pm_engages_with_debate_pass"] is True
        assert grade["comment"] == "pass"

    def test_too_few_counter_arguments_fails_contrarian_check(self) -> None:
        bad_contrarian = {**_GOOD_CONTRARIAN, "counter_arguments": ["Only one point."]}
        grade = grade_debate_snapshot(
            name="bad",
            contrarian=bad_contrarian,
            debate_rounds=_GOOD_ROUNDS,
            decision=_GOOD_DECISION,
        )
        assert grade["contrarian_disagrees_pass"] is False
        assert grade["overall_pass"] is False
        assert "counter_arguments" in grade["comment"]

    def test_exactly_the_minimum_counter_arguments_passes(self) -> None:
        assert CONTRARIAN_MIN_COUNTER_ARGUMENTS == 3
        contrarian = {
            **_GOOD_CONTRARIAN,
            "counter_arguments": _GOOD_CONTRARIAN["counter_arguments"][:3],
        }
        grade = grade_debate_snapshot(
            name="boundary",
            contrarian=contrarian,
            debate_rounds=_GOOD_ROUNDS,
            decision=_GOOD_DECISION,
        )
        assert grade["contrarian_disagrees_pass"] is True

    def test_zero_bear_conviction_fails_contrarian_check(self) -> None:
        bad_contrarian = {**_GOOD_CONTRARIAN, "bear_conviction": 0}
        grade = grade_debate_snapshot(
            name="bad",
            contrarian=bad_contrarian,
            debate_rounds=_GOOD_ROUNDS,
            decision=_GOOD_DECISION,
        )
        assert grade["contrarian_disagrees_pass"] is False

    def test_single_agent_round_fails_multi_agent_check(self) -> None:
        single_agent_round = [
            {
                "round_number": 1,
                "agent_responses": {
                    "fundamental": "Fundamental Analyst holds its view.",
                    "technical": (
                        "Technical Analyst has no position this "
                        "round (data unavailable)."
                    ),
                    "sentiment": (
                        "News Sentiment Agent has no position "
                        "this round (data unavailable)."
                    ),
                    "macro": (
                        "Macro Economist has no position this "
                        "round (data unavailable)."
                    ),
                    "risk": (
                        "Risk Officer has no position this round " "(data unavailable)."
                    ),
                },
                "contrarian": "Some challenge.",
                "completed_at": "2026-01-01T00:00:00Z",
            }
        ]
        grade = grade_debate_snapshot(
            name="bad",
            contrarian=_GOOD_CONTRARIAN,
            debate_rounds=single_agent_round,
            decision=_GOOD_DECISION,
        )
        assert grade["multi_agent_engagement_pass"] is False
        assert grade["overall_pass"] is False

    def test_empty_debate_rounds_fails_multi_agent_check(self) -> None:
        grade = grade_debate_snapshot(
            name="bad",
            contrarian=_GOOD_CONTRARIAN,
            debate_rounds=[],
            decision=_GOOD_DECISION,
        )
        assert grade["multi_agent_engagement_pass"] is False

    def test_repeated_counter_arguments_fail_novelty_check(self) -> None:
        bad_contrarian = {
            **_GOOD_CONTRARIAN,
            "counter_arguments": [
                "Margins are declining due to rising input costs across the board.",
                "Margins are declining due to rising input costs across "
                "the whole business.",
                "A third, genuinely distinct point about leadership "
                "transition risk.",
            ],
        }
        grade = grade_debate_snapshot(
            name="bad",
            contrarian=bad_contrarian,
            debate_rounds=_GOOD_ROUNDS,
            decision=_GOOD_DECISION,
        )
        assert grade["novelty_pass"] is False
        assert grade["overall_pass"] is False
        assert "near-duplicate" in grade["comment"]

    def test_repetition_across_counter_arguments_and_overlooked_risks(self) -> None:
        """
        Novelty must be checked across BOTH counter_arguments AND
        overlooked_risks combined, not just within counter_arguments
        alone.
        """
        bad_contrarian = {
            **_GOOD_CONTRARIAN,
            "counter_arguments": [
                "Revenue growth has lagged the two largest peers for years.",
                "Leadership transition adds meaningful execution risk right now.",
                "Technical momentum looks weaker than the headline trend suggests.",
            ],
            "overlooked_risks": [
                "Revenue growth has lagged the two biggest peers for many years.",
            ],
        }
        grade = grade_debate_snapshot(
            name="bad",
            contrarian=bad_contrarian,
            debate_rounds=_GOOD_ROUNDS,
            decision=_GOOD_DECISION,
        )
        assert grade["novelty_pass"] is False

    def test_empty_contrarian_response_fails_pm_engagement_check(self) -> None:
        bad_decision = {**_GOOD_DECISION, "contrarian_response": ""}
        grade = grade_debate_snapshot(
            name="bad",
            contrarian=_GOOD_CONTRARIAN,
            debate_rounds=_GOOD_ROUNDS,
            decision=bad_decision,
        )
        assert grade["pm_engages_with_debate_pass"] is False
        assert grade["overall_pass"] is False

    def test_verbatim_echo_fails_pm_engagement_check(self) -> None:
        """
        The PM simply copy-pasting the Contrarian's strongest_argument
        verbatim must NOT count as "engaging with the debate content".
        """
        bad_decision = {
            **_GOOD_DECISION,
            "contrarian_response": _GOOD_CONTRARIAN["strongest_argument"],
        }
        grade = grade_debate_snapshot(
            name="bad",
            contrarian=_GOOD_CONTRARIAN,
            debate_rounds=_GOOD_ROUNDS,
            decision=bad_decision,
        )
        assert grade["pm_engages_with_debate_pass"] is False
        assert "echo" in grade["comment"] or "verbatim" in grade["comment"]

    def test_verbatim_echo_embedded_in_longer_text_still_fails(self) -> None:
        bad_decision = {
            **_GOOD_DECISION,
            "contrarian_response": (
                f"As the Contrarian noted: {_GOOD_CONTRARIAN['strongest_argument']} "
                "We take no further view."
            ),
        }
        grade = grade_debate_snapshot(
            name="bad",
            contrarian=_GOOD_CONTRARIAN,
            debate_rounds=_GOOD_ROUNDS,
            decision=bad_decision,
        )
        assert grade["pm_engages_with_debate_pass"] is False

    def test_missing_fields_are_graded_as_fail_not_raise(self) -> None:
        grade = grade_debate_snapshot(
            name="empty",
            contrarian={},
            debate_rounds=[],
            decision={},
        )
        assert grade["overall_pass"] is False
        assert grade["contrarian_disagrees_pass"] is False
        assert grade["multi_agent_engagement_pass"] is False
        assert grade["pm_engages_with_debate_pass"] is False

    def test_malformed_field_types_do_not_raise(self) -> None:
        grade = grade_debate_snapshot(
            name="malformed",
            contrarian={"counter_arguments": "not-a-list", "bear_conviction": "high"},
            debate_rounds="not-a-list-or-tuple",  # type: ignore[arg-type]
            decision={"contrarian_response": 12345},
        )
        assert grade["overall_pass"] is False


# ---------------------------------------------------------------------------
# 4. compute_pass_rate() / meets_debate_quality_target()
# ---------------------------------------------------------------------------


class TestAggregation:
    def _grade(self, overall_pass: bool) -> Any:
        return {
            "name": "x",
            "contrarian_disagrees_pass": overall_pass,
            "multi_agent_engagement_pass": overall_pass,
            "novelty_pass": overall_pass,
            "pm_engages_with_debate_pass": overall_pass,
            "overall_pass": overall_pass,
            "comment": "pass" if overall_pass else "fail",
        }

    def test_all_pass(self) -> None:
        grades = [self._grade(True) for _ in range(5)]
        passed, total = compute_pass_rate(grades)
        assert (passed, total) == (5, 5)
        assert meets_debate_quality_target(passed, total) is True

    def test_one_failure_fails_all_or_nothing_target(self) -> None:
        grades = [self._grade(True) for _ in range(4)] + [self._grade(False)]
        passed, total = compute_pass_rate(grades)
        assert (passed, total) == (4, 5)
        assert meets_debate_quality_target(passed, total) is False

    def test_empty_dataset_does_not_vacuously_pass(self) -> None:
        assert meets_debate_quality_target(0, 0) is False


# ---------------------------------------------------------------------------
# 5. debate_eval_target()
# ---------------------------------------------------------------------------


class TestDebateEvalTarget:
    def test_returns_grade_dict_for_valid_inputs(self) -> None:
        result = debate_eval_target(
            {
                "name": "test",
                "contrarian": _GOOD_CONTRARIAN,
                "debate_rounds": _GOOD_ROUNDS,
                "decision": _GOOD_DECISION,
            }
        )
        assert result["overall_pass"] is True

    def test_missing_keys_returns_failing_grade_not_raises(self) -> None:
        result = debate_eval_target({})
        assert result["overall_pass"] is False

    def test_malformed_nested_values_do_not_raise(self) -> None:
        result = debate_eval_target(
            {
                "name": "bad",
                "contrarian": "not-a-dict",
                "debate_rounds": 42,
                "decision": None,
            }
        )
        assert result["overall_pass"] is False


# ---------------------------------------------------------------------------
# 6. LangSmith evaluator wrappers -- (run, example) -> dict
# ---------------------------------------------------------------------------


def _make_run(grade_overrides: dict[str, Any]) -> Any:
    base = {
        "contrarian_disagrees_pass": True,
        "multi_agent_engagement_pass": True,
        "novelty_pass": True,
        "pm_engages_with_debate_pass": True,
        "comment": "pass",
    }
    base.update(grade_overrides)
    return SimpleNamespace(outputs=base, inputs={})


class TestLangSmithEvaluatorWrappers:
    def test_contrarian_disagrees_evaluator_pass(self) -> None:
        run = _make_run({})
        result = contrarian_disagrees_evaluator(run, SimpleNamespace(outputs={}))
        assert result["key"] == "contrarian_disagrees"
        assert result["score"] == 1

    def test_contrarian_disagrees_evaluator_fail(self) -> None:
        run = _make_run({"contrarian_disagrees_pass": False})
        result = contrarian_disagrees_evaluator(run, SimpleNamespace(outputs={}))
        assert result["score"] == 0

    def test_multi_agent_engagement_evaluator_fail(self) -> None:
        run = _make_run({"multi_agent_engagement_pass": False})
        result = multi_agent_engagement_evaluator(run, SimpleNamespace(outputs={}))
        assert result["key"] == "multi_agent_engagement"
        assert result["score"] == 0

    def test_novelty_evaluator_fail(self) -> None:
        run = _make_run({"novelty_pass": False})
        result = novelty_evaluator(run, SimpleNamespace(outputs={}))
        assert result["key"] == "novelty"
        assert result["score"] == 0

    def test_pm_engages_with_debate_evaluator_fail(self) -> None:
        run = _make_run({"pm_engages_with_debate_pass": False})
        result = pm_engages_with_debate_evaluator(run, SimpleNamespace(outputs={}))
        assert result["key"] == "pm_engages_with_debate"
        assert result["score"] == 0

    def test_evaluators_never_raise_on_malformed_run_outputs(self) -> None:
        run = SimpleNamespace(outputs="not-a-dict", inputs={})
        result = contrarian_disagrees_evaluator(run, SimpleNamespace(outputs={}))
        assert result["score"] == 0

    def test_evaluators_never_raise_on_missing_outputs_attribute(self) -> None:
        run = SimpleNamespace(inputs={})  # no .outputs at all
        result = novelty_evaluator(run, SimpleNamespace(outputs={}))
        assert result["score"] == 0


# ---------------------------------------------------------------------------
# 7. Full real dataset meets T-070's actual acceptance criteria
# ---------------------------------------------------------------------------


class TestFullDatasetMeetsTargets:
    """
    Runs the ENTIRE real dataset through the real, un-mocked grading
    pipeline and asserts T-070's literal acceptance criteria. Possible
    here (and not for T-068's Fundamental Analyst eval) for the same
    reason it was possible for T-069: grading a debate snapshot has no
    network/LLM dependency -- it operates entirely on already-produced
    state.
    """

    def test_all_five_snapshots_pass_every_check(self) -> None:
        grades = [
            grade_debate_snapshot(
                name=ex["name"],
                contrarian=ex["contrarian"],
                debate_rounds=ex["debate_rounds"],
                decision=ex["decision"],
            )
            for ex in DEBATE_EVAL_DATASET
        ]
        passed, total = compute_pass_rate(grades)
        failures = [g for g in grades if not g["overall_pass"]]
        assert meets_debate_quality_target(passed, total), (
            f"Only {passed}/{total} snapshots passed every check. "
            f"Failures: {failures}"
        )

    @pytest.mark.parametrize("example", DEBATE_EVAL_DATASET, ids=lambda ex: ex["name"])
    def test_every_snapshot_individually_passes(self, example: Any) -> None:
        """
        Parametrized per-snapshot so a CI failure names the exact
        snapshot and check that broke.
        """
        grade = grade_debate_snapshot(
            name=example["name"],
            contrarian=example["contrarian"],
            debate_rounds=example["debate_rounds"],
            decision=example["decision"],
        )
        assert grade["overall_pass"], grade["comment"]

    @pytest.mark.parametrize("example", DEBATE_EVAL_DATASET, ids=lambda ex: ex["name"])
    def test_every_snapshot_contrarian_disagrees(self, example: Any) -> None:
        assert len(example["contrarian"]["counter_arguments"]) >= 3

    def test_novelty_threshold_constant_is_documented_value(self) -> None:
        assert NOVELTY_SIMILARITY_THRESHOLD == 0.6
