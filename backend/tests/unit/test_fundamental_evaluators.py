# backend/tests/unit/test_fundamental_evaluators.py
"""
Unit tests for T-068: Fundamental Analyst LangSmith Eval.

Test strategy (mirrors EVAL_FRAMEWORK_DESIGN.md §4's CI-scoping guidance):
  1. Dataset shape          -- FUNDAMENTAL_EVAL_DATASET has exactly 5 rows,
                                unique tickers, valid buckets, and matches
                                the strong/strong/neutral/weak/insufficient
                                spread the design doc specifies
  2. bucket_matches()       -- pure range/tolerance logic, no I/O
  3. grade_fundamental_output() -- the full 3-check rubric against
                                synthetic (not real) agent outputs
  4. compute_accuracy() / meets_target() -- aggregation logic
  5. fundamental_eval_target()  -- calls the REAL agent core but with
                                mocked tools + LLM (same mocking pattern
                                as test_fundamental_analyst.py), so this
                                stays a fast, deterministic, offline test
  6. LangSmith evaluator wrappers -- (run, example) -> dict, using
                                lightweight SimpleNamespace stand-ins for
                                langsmith.schemas.Run/Example rather than
                                a real LangSmith call

None of these tests call a real LLM, hit the network, or require a
LANGSMITH_API_KEY -- the real, LangSmith-backed evaluation run lives in
scripts/run_eval_fundamental.py (manual, not part of CI), exactly per
EVAL_FRAMEWORK_DESIGN.md §4's split between CI-safe evaluator-logic tests
and a manually-run real experiment.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402

from backend.evals.fundamental_eval_dataset import (  # noqa: E402
    FUNDAMENTAL_EVAL_DATASET,
)
from backend.evals.fundamental_evaluators import (  # noqa: E402
    ACCURACY_TARGET_PCT,
    BUCKET_TOLERANCE,
    bucket_matches,
    compute_accuracy,
    directional_accuracy_evaluator,
    fundamental_eval_target,
    grade_fundamental_output,
    honest_abstention_evaluator,
    meets_target,
    schema_validity_evaluator,
)

# ---------------------------------------------------------------------------
# 1. Dataset shape
# ---------------------------------------------------------------------------


class TestDatasetShape:
    def test_has_exactly_five_examples(self) -> None:
        assert len(FUNDAMENTAL_EVAL_DATASET) == 5

    def test_tickers_are_unique(self) -> None:
        tickers = [ex["ticker"] for ex in FUNDAMENTAL_EVAL_DATASET]
        assert len(tickers) == len(set(tickers))

    def test_every_bucket_is_valid(self) -> None:
        valid_buckets = {"strong", "neutral", "weak", "insufficient"}
        for ex in FUNDAMENTAL_EVAL_DATASET:
            assert ex["expected_bucket"] in valid_buckets

    def test_matches_designed_bucket_spread(self) -> None:
        """
        EVAL_FRAMEWORK_DESIGN.md §3.1 specifies 2 strong, 1 neutral,
        1 weak, 1 insufficient -- exactly the spread that keeps the eval
        from passing by always guessing "medium".
        """
        buckets = [ex["expected_bucket"] for ex in FUNDAMENTAL_EVAL_DATASET]
        assert buckets.count("strong") == 2
        assert buckets.count("neutral") == 1
        assert buckets.count("weak") == 1
        assert buckets.count("insufficient") == 1

    def test_every_example_has_a_rationale(self) -> None:
        for ex in FUNDAMENTAL_EVAL_DATASET:
            assert len(ex["rationale"]) > 10

    def test_insufficient_example_uses_a_deliberately_invalid_ticker(self) -> None:
        insufficient = [
            ex
            for ex in FUNDAMENTAL_EVAL_DATASET
            if ex["expected_bucket"] == "insufficient"
        ]
        assert len(insufficient) == 1
        # Not a real NSE ticker -- deterministic empty-data path, see
        # fundamental_eval_dataset.py's own docstring for why.
        assert "PLACEHOLDER" in insufficient[0]["ticker"]


# ---------------------------------------------------------------------------
# 2. bucket_matches()
# ---------------------------------------------------------------------------


class TestBucketMatches:
    @pytest.mark.parametrize("score", [7, 8, 9, 10])
    def test_strong_bucket_accepts_high_scores(self, score: int) -> None:
        assert bucket_matches(score, "strong") is True

    @pytest.mark.parametrize("score", [4, 5, 6])
    def test_neutral_bucket_accepts_mid_scores(self, score: int) -> None:
        assert bucket_matches(score, "neutral") is True

    @pytest.mark.parametrize("score", [1, 2, 3])
    def test_weak_bucket_accepts_low_scores(self, score: int) -> None:
        assert bucket_matches(score, "weak") is True

    def test_strong_bucket_tolerance_accepts_boundary_minus_one(self) -> None:
        # strong range is (7, 10); with tolerance 1, score=6 should pass.
        assert BUCKET_TOLERANCE == 1
        assert bucket_matches(6, "strong") is True

    def test_strong_bucket_rejects_far_below_range(self) -> None:
        assert bucket_matches(3, "strong") is False

    def test_weak_bucket_rejects_far_above_range(self) -> None:
        assert bucket_matches(8, "weak") is False

    def test_none_score_never_matches(self) -> None:
        assert bucket_matches(None, "strong") is False
        assert bucket_matches(None, "neutral") is False
        assert bucket_matches(None, "weak") is False

    def test_unknown_bucket_name_returns_false(self) -> None:
        assert bucket_matches(8, "not_a_real_bucket") is False

    def test_insufficient_bucket_has_no_numeric_range(self) -> None:
        # "insufficient" is graded by abstention, not a score range --
        # bucket_matches should never report a match for it.
        assert bucket_matches(5, "insufficient") is False


# ---------------------------------------------------------------------------
# 3. grade_fundamental_output()
# ---------------------------------------------------------------------------


class TestGradeFundamentalOutput:
    def test_strong_company_correct_score_passes(self) -> None:
        grade = grade_fundamental_output(
            ticker="TCS.NS",
            expected_bucket="strong",
            actual_score=9,
            actual_data_quality="sufficient",
            actual_error=None,
        )
        assert grade["overall_pass"] is True
        assert grade["directional_pass"] is True
        assert grade["abstention_pass"] is True
        assert grade["schema_pass"] is True

    def test_strong_company_low_score_fails_directional(self) -> None:
        grade = grade_fundamental_output(
            ticker="TCS.NS",
            expected_bucket="strong",
            actual_score=2,
            actual_data_quality="sufficient",
            actual_error=None,
        )
        assert grade["overall_pass"] is False
        assert grade["directional_pass"] is False
        assert "not in expected" in grade["comment"]

    def test_insufficient_case_correct_abstention_passes(self) -> None:
        grade = grade_fundamental_output(
            ticker="AIRPEVALPLACEHOLDER.NS",
            expected_bucket="insufficient",
            actual_score=None,
            actual_data_quality="insufficient",
            actual_error=None,
        )
        assert grade["overall_pass"] is True
        assert grade["abstention_pass"] is True
        # Directional/schema checks are not applicable for the abstention
        # row -- they must not drag down overall_pass.
        assert grade["directional_pass"] is True
        assert grade["schema_pass"] is True

    def test_insufficient_case_fabricated_score_fails_abstention(self) -> None:
        """
        The hard-fail case EVAL_FRAMEWORK_DESIGN.md §3.1 calls out
        explicitly: a confident wrong number on the thin-data example is
        a hard fail, not a partial-credit miss.
        """
        grade = grade_fundamental_output(
            ticker="AIRPEVALPLACEHOLDER.NS",
            expected_bucket="insufficient",
            actual_score=5,
            actual_data_quality="sufficient",
            actual_error=None,
        )
        assert grade["overall_pass"] is False
        assert grade["abstention_pass"] is False
        assert "expected honest abstention" in grade["comment"]

    def test_error_set_on_non_abstention_example_fails_schema(self) -> None:
        grade = grade_fundamental_output(
            ticker="HINDUNILVR.NS",
            expected_bucket="strong",
            actual_score=8,
            actual_data_quality="sufficient",
            actual_error="unexpected tool failure",
        )
        assert grade["overall_pass"] is False
        assert grade["schema_pass"] is False
        assert "unexpected error set" in grade["comment"]

    def test_passing_grade_has_pass_comment(self) -> None:
        grade = grade_fundamental_output(
            ticker="TCS.NS",
            expected_bucket="strong",
            actual_score=9,
            actual_data_quality="sufficient",
            actual_error=None,
        )
        assert grade["comment"] == "pass"

    def test_never_raises_on_out_of_range_score(self) -> None:
        # Pydantic's own ge=1/le=10 validators would normally prevent this,
        # but the grading function itself must stay defensive and simply
        # grade it as a directional miss rather than raising.
        grade = grade_fundamental_output(
            ticker="WEIRD.NS",
            expected_bucket="strong",
            actual_score=999,
            actual_data_quality="sufficient",
            actual_error=None,
        )
        assert grade["overall_pass"] is False


# ---------------------------------------------------------------------------
# 4. compute_accuracy() / meets_target()
# ---------------------------------------------------------------------------


class TestComputeAccuracy:
    def _grade(self, overall_pass: bool) -> Any:
        return {
            "ticker": "X",
            "expected_bucket": "strong",
            "actual_score": 8,
            "actual_data_quality": "sufficient",
            "directional_pass": overall_pass,
            "abstention_pass": True,
            "schema_pass": True,
            "overall_pass": overall_pass,
            "comment": "pass" if overall_pass else "fail",
        }

    def test_all_pass_is_100_percent(self) -> None:
        grades = [self._grade(True) for _ in range(5)]
        assert compute_accuracy(grades) == 100.0

    def test_all_fail_is_0_percent(self) -> None:
        grades = [self._grade(False) for _ in range(5)]
        assert compute_accuracy(grades) == 0.0

    def test_four_of_five_is_80_percent(self) -> None:
        grades = [self._grade(True) for _ in range(4)] + [self._grade(False)]
        assert compute_accuracy(grades) == 80.0

    def test_three_of_five_is_60_percent(self) -> None:
        grades = [self._grade(True) for _ in range(3)] + [
            self._grade(False) for _ in range(2)
        ]
        assert compute_accuracy(grades) == 60.0

    def test_empty_list_returns_zero_not_raises(self) -> None:
        assert compute_accuracy([]) == 0.0

    def test_meets_target_above_70(self) -> None:
        assert meets_target(80.0) is True

    def test_meets_target_below_70(self) -> None:
        assert meets_target(60.0) is False

    def test_meets_target_at_exactly_70_fails(self) -> None:
        # Task spec says ">70%" -- exactly 70% must not count as meeting it.
        assert ACCURACY_TARGET_PCT == 70.0
        assert meets_target(70.0) is False


# ---------------------------------------------------------------------------
# 5. fundamental_eval_target() -- real core function, mocked tools + LLM
# ---------------------------------------------------------------------------

# Reuses the same minimal mock shapes as test_fundamental_analyst.py.
_FINANCIALS_GOOD: dict[str, Any] = {
    "years_available": 4,
    "income_statement": [
        {
            "fiscal_year": "FY 2024",
            "revenue_crores": 240_890.0,
            "net_income_crores": 46_099.0,
            "net_margin_pct": 19.1,
            "operating_margin_pct": 24.5,
            "gross_margin_pct": 35.7,
        },
        {
            "fiscal_year": "FY 2021",
            "revenue_crores": 164_000.0,
            "net_income_crores": 33_000.0,
            "net_margin_pct": 20.1,
        },
    ],
    "balance_sheet": [{"debt_to_equity": 0.1, "current_ratio": 2.5}],
    "cash_flow": [{"free_cash_flow_crores": 40_000.0, "fcf_margin_pct": 16.6}],
    "data_warnings": [],
}
_RATIOS_GOOD: dict[str, Any] = {
    "pe_ratio": 28.0,
    "pb_ratio": 12.0,
    "roe_pct": 46.2,
    "roce_pct": 58.0,
    "debt_to_equity": 0.1,
    "ev_to_ebitda": 20.0,
}
_LLM_JSON_RESPONSE = (
    '{"strengths": ["Strong ROE of 46.2%"], '
    '"risks": ["Premium valuation at 28x PE"], '
    '"summary": "High-quality compounder with strong fundamentals."}'
)


def _make_llm_response(text: str) -> Any:
    mock_response = MagicMock()
    mock_response.content = text
    return mock_response


class TestFundamentalEvalTarget:
    def test_returns_serialisable_dict_on_success(self) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _make_llm_response(_LLM_JSON_RESPONSE)

        with (
            patch("backend.agents.fundamental_analyst.fetch_financials") as mock_fin,
            patch("backend.agents.fundamental_analyst.fetch_ratios") as mock_rat,
            patch(
                "backend.agents.fundamental_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_fin.invoke.return_value = _FINANCIALS_GOOD
            mock_rat.invoke.return_value = _RATIOS_GOOD

            result = fundamental_eval_target(
                {"company_name": "Tata Consultancy Services", "ticker": "TCS.NS"}
            )

        assert isinstance(result, dict)
        assert result["error"] is None
        assert result["score"] is not None
        assert 1 <= result["score"] <= 10

    def test_returns_insufficient_for_empty_data(self) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _make_llm_response(_LLM_JSON_RESPONSE)

        with (
            patch("backend.agents.fundamental_analyst.fetch_financials") as mock_fin,
            patch("backend.agents.fundamental_analyst.fetch_ratios") as mock_rat,
            patch(
                "backend.agents.fundamental_analyst.get_llm",
                return_value=mock_llm,
            ),
        ):
            mock_fin.invoke.return_value = {}
            mock_rat.invoke.return_value = {}

            result = fundamental_eval_target(
                {
                    "company_name": "AIRP Eval Placeholder Co",
                    "ticker": "AIRPEVALPLACEHOLDER.NS",
                }
            )

        assert result["score"] is None
        assert result["data_quality"] == "insufficient"

    def test_never_raises_when_core_function_crashes(self) -> None:
        with patch(
            "backend.evals.fundamental_evaluators._run_fundamental_analysis_core",
            side_effect=RuntimeError("boom"),
        ):
            result = fundamental_eval_target(
                {"company_name": "Whatever Co", "ticker": "WHAT.NS"}
            )

        assert result["error"] is not None
        assert "eval target crashed" in result["error"]


# ---------------------------------------------------------------------------
# 6. LangSmith evaluator wrappers -- (run, example) -> dict
# ---------------------------------------------------------------------------


def _make_run(outputs: dict[str, Any], inputs: dict[str, Any] | None = None) -> Any:
    return SimpleNamespace(outputs=outputs, inputs=inputs or {"ticker": "TCS.NS"})


def _make_example(expected_bucket: str) -> Any:
    return SimpleNamespace(outputs={"expected_bucket": expected_bucket})


class TestLangSmithEvaluatorWrappers:
    def test_directional_accuracy_evaluator_pass(self) -> None:
        run = _make_run({"score": 9, "data_quality": "sufficient", "error": None})
        example = _make_example("strong")
        result = directional_accuracy_evaluator(run, example)
        assert result["key"] == "directional_accuracy"
        assert result["score"] == 1

    def test_directional_accuracy_evaluator_fail(self) -> None:
        run = _make_run({"score": 2, "data_quality": "sufficient", "error": None})
        example = _make_example("strong")
        result = directional_accuracy_evaluator(run, example)
        assert result["score"] == 0

    def test_honest_abstention_evaluator_pass(self) -> None:
        run = _make_run({"score": None, "data_quality": "insufficient", "error": None})
        example = _make_example("insufficient")
        result = honest_abstention_evaluator(run, example)
        assert result["key"] == "honest_abstention"
        assert result["score"] == 1

    def test_honest_abstention_evaluator_fail_on_fabricated_score(self) -> None:
        run = _make_run({"score": 5, "data_quality": "sufficient", "error": None})
        example = _make_example("insufficient")
        result = honest_abstention_evaluator(run, example)
        assert result["score"] == 0

    def test_schema_validity_evaluator_pass(self) -> None:
        run = _make_run({"score": 8, "data_quality": "sufficient", "error": None})
        example = _make_example("strong")
        result = schema_validity_evaluator(run, example)
        assert result["key"] == "schema_validity"
        assert result["score"] == 1

    def test_schema_validity_evaluator_fail_on_error(self) -> None:
        run = _make_run(
            {"score": 8, "data_quality": "sufficient", "error": "tool timeout"}
        )
        example = _make_example("strong")
        result = schema_validity_evaluator(run, example)
        assert result["score"] == 0

    def test_evaluators_never_raise_on_malformed_run_outputs(self) -> None:
        run = SimpleNamespace(outputs="not-a-dict", inputs={})
        example = _make_example("strong")

        # Must gracefully grade as a fail, not raise.
        result = directional_accuracy_evaluator(run, example)
        assert result["score"] == 0

    def test_evaluators_never_raise_on_missing_outputs_attribute(self) -> None:
        run = SimpleNamespace(inputs={})  # no .outputs at all
        example = _make_example("strong")

        result = schema_validity_evaluator(run, example)
        assert result["score"] == 0
