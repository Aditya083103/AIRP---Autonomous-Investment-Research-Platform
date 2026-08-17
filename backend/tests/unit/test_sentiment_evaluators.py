# backend/tests/unit/test_sentiment_evaluators.py
"""
Unit tests for T-069: News Sentiment Agent LangSmith Eval.

Test strategy:
  1. Dataset shape           -- 10 direction sets (4 pos/4 neg/2 neutral)
                                 + 3 scandal sets, every example checked
                                 against the REAL sentiment_analyst.py
                                 keyword lists (not hand-verified only)
  2. score_news_set()        -- reuses the real agent's scoring functions,
                                 verified against a few hand-computed cases
  3. direction_matches()     -- pure comparison logic
  4. grade_direction_example() / grade_scandal_example() -- full rubric
  5. compute_direction_accuracy() / meets_direction_target()
  6. compute_scandal_detection() / meets_scandal_target()
  7. sentiment_eval_target() -- deterministic target function, no mocking
                                 needed (no network/LLM dependency at all)
  8. LangSmith evaluator wrappers -- (run, example) -> dict
  9. TestFullDatasetMeetsTargets -- runs the ENTIRE real dataset through
                                 the real grading pipeline and asserts it
                                 meets T-069's actual acceptance criteria
                                 (>80% directional accuracy, 3-of-3 red-flag
                                 detection). This is possible -- and
                                 deliberately done -- specifically because
                                 sentiment scoring has zero network/LLM
                                 dependency, unlike T-068's Fundamental
                                 Analyst eval; see
                                 backend/evals/sentiment_evaluators.py's
                                 module docstring for why.

None of these tests call a real LLM or hit the network. This entire suite
runs fully offline, deterministically, every time.
"""
from __future__ import annotations

import os

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "test")

from types import SimpleNamespace  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402

from backend.agents.sentiment_analyst import (  # noqa: E402
    NEGATIVE_KEYWORDS,
    POSITIVE_KEYWORDS,
    RED_FLAG_PHRASES,
)
from backend.evals.sentiment_eval_dataset import (  # noqa: E402
    SENTIMENT_DIRECTION_DATASET,
    SENTIMENT_SCANDAL_DATASET,
    ArticleInput,
)
from backend.evals.sentiment_evaluators import (  # noqa: E402
    DIRECTION_ACCURACY_TARGET_PCT,
    compute_direction_accuracy,
    compute_scandal_detection,
    direction_accuracy_evaluator,
    direction_matches,
    grade_direction_example,
    grade_scandal_example,
    meets_direction_target,
    meets_scandal_target,
    no_false_alarm_evaluator,
    red_flag_detection_evaluator,
    score_news_set,
    sentiment_eval_target,
)

# ---------------------------------------------------------------------------
# 1. Dataset shape
# ---------------------------------------------------------------------------


def _article_text(article: ArticleInput) -> str:
    return f"{article['title']} {article['description']}".lower()


class TestDatasetShape:
    def test_direction_dataset_has_exactly_ten_examples(self) -> None:
        assert len(SENTIMENT_DIRECTION_DATASET) == 10

    def test_scandal_dataset_has_exactly_three_examples(self) -> None:
        assert len(SENTIMENT_SCANDAL_DATASET) == 3

    def test_direction_dataset_names_are_unique(self) -> None:
        names = [ex["name"] for ex in SENTIMENT_DIRECTION_DATASET]
        assert len(names) == len(set(names))

    def test_scandal_dataset_names_are_unique(self) -> None:
        names = [ex["name"] for ex in SENTIMENT_SCANDAL_DATASET]
        assert len(names) == len(set(names))

    def test_matches_designed_direction_spread(self) -> None:
        """
        EVAL_FRAMEWORK_DESIGN.md §3.2 specifies 4 positive, 4 negative,
        2 flat/mixed.
        """
        directions = [ex["expected_direction"] for ex in SENTIMENT_DIRECTION_DATASET]
        assert directions.count("positive") == 4
        assert directions.count("negative") == 4
        assert directions.count("neutral") == 2

    def test_every_direction_example_has_at_least_one_article(self) -> None:
        for ex in SENTIMENT_DIRECTION_DATASET:
            assert len(ex["articles"]) >= 1

    def test_every_scandal_example_has_expected_keywords(self) -> None:
        for ex in SENTIMENT_SCANDAL_DATASET:
            assert len(ex["expected_flag_keywords"]) >= 1

    def test_positive_direction_examples_contain_a_real_positive_keyword(self) -> None:
        """
        Verified against the REAL POSITIVE_KEYWORDS list (imported from
        sentiment_analyst.py) rather than trusted by inspection -- if that
        list is ever edited, a dataset example that no longer matches
        anything fails here instead of silently grading wrong.
        """
        for ex in SENTIMENT_DIRECTION_DATASET:
            if ex["expected_direction"] != "positive":
                continue
            text = " ".join(_article_text(a) for a in ex["articles"])
            assert any(kw in text for kw in POSITIVE_KEYWORDS), (
                f"{ex['name']} expected positive but matches no "
                "POSITIVE_KEYWORDS entry"
            )

    def test_negative_direction_examples_contain_a_real_negative_keyword(self) -> None:
        for ex in SENTIMENT_DIRECTION_DATASET:
            if ex["expected_direction"] != "negative":
                continue
            text = " ".join(_article_text(a) for a in ex["articles"])
            assert any(kw in text for kw in NEGATIVE_KEYWORDS), (
                f"{ex['name']} expected negative but matches no "
                "NEGATIVE_KEYWORDS entry"
            )

    def test_direction_examples_never_contain_a_red_flag_phrase(self) -> None:
        """
        The "no false alarms" rubric row -- none of the 10 direction sets
        should ever be able to trip a red flag, verified against the REAL
        RED_FLAG_PHRASES list.
        """
        for ex in SENTIMENT_DIRECTION_DATASET:
            text = " ".join(_article_text(a) for a in ex["articles"])
            matched = [p for p in RED_FLAG_PHRASES if p in text]
            assert matched == [], (
                f"{ex['name']} unexpectedly contains RED_FLAG_PHRASES "
                f"entries {matched} -- would cause a false-alarm failure"
            )

    def test_scandal_examples_each_contain_a_real_red_flag_phrase(self) -> None:
        for ex in SENTIMENT_SCANDAL_DATASET:
            text = " ".join(_article_text(a) for a in ex["articles"])
            matched = [p for p in RED_FLAG_PHRASES if p in text]
            assert matched, f"{ex['name']} matches no RED_FLAG_PHRASES entry"


# ---------------------------------------------------------------------------
# 2. score_news_set() -- reuses the real agent's own scoring functions
# ---------------------------------------------------------------------------


class TestScoreNewsSet:
    def test_strongly_positive_article_scores_positive(self) -> None:
        articles: tuple[ArticleInput, ...] = (
            {
                "title": "Company wins record order",
                "description": "Strong growth and robust profit expansion",
            },
        )
        score, label, flags = score_news_set(articles)
        assert score > 0
        assert label in ("positive", "very_positive")
        assert flags == []

    def test_strongly_negative_article_scores_negative(self) -> None:
        articles: tuple[ArticleInput, ...] = (
            {
                "title": "Company misses estimates, cuts guidance",
                "description": "Stock falls as demand weakens and margins decline",
            },
        )
        score, label, flags = score_news_set(articles)
        assert score < 0
        assert label in ("negative", "very_negative")
        assert flags == []

    def test_no_keyword_article_is_neutral(self) -> None:
        articles: tuple[ArticleInput, ...] = (
            {
                "title": "Company schedules shareholder meeting",
                "description": "Routine administrative agenda items",
            },
        )
        score, label, flags = score_news_set(articles)
        assert score == 0.0
        assert label == "neutral"
        assert flags == []

    def test_scandal_text_triggers_red_flags(self) -> None:
        articles: tuple[ArticleInput, ...] = (
            {
                "title": "SEBI launches investigation into accounting fraud",
                "description": "Probe finds whistleblower complaint credible",
            },
        )
        _score, _label, flags = score_news_set(articles)
        assert len(flags) >= 1

    def test_empty_article_tuple_is_neutral_no_flags(self) -> None:
        score, label, flags = score_news_set(())
        assert score == 0.0
        assert label == "neutral"
        assert flags == []


# ---------------------------------------------------------------------------
# 3. direction_matches()
# ---------------------------------------------------------------------------


class TestDirectionMatches:
    def test_positive_expected_passes_on_positive_score(self) -> None:
        assert direction_matches(0.3, "positive", "positive") is True

    def test_positive_expected_fails_on_zero_score(self) -> None:
        assert direction_matches(0.0, "neutral", "positive") is False

    def test_positive_expected_fails_on_negative_score(self) -> None:
        assert direction_matches(-0.2, "negative", "positive") is False

    def test_negative_expected_passes_on_negative_score(self) -> None:
        assert direction_matches(-0.3, "negative", "negative") is True

    def test_negative_expected_fails_on_positive_score(self) -> None:
        assert direction_matches(0.2, "positive", "negative") is False

    def test_neutral_expected_passes_when_label_is_neutral(self) -> None:
        assert direction_matches(0.0, "neutral", "neutral") is True

    def test_neutral_expected_fails_when_label_is_not_neutral(self) -> None:
        # Delegates to the real label, not a re-derived score boundary --
        # a label of 'positive' at a score that happens to be small still
        # fails the neutral expectation.
        assert direction_matches(0.15, "positive", "neutral") is False

    def test_unknown_expected_direction_returns_false(self) -> None:
        assert direction_matches(0.5, "very_positive", "sideways") is False


# ---------------------------------------------------------------------------
# 4. grade_direction_example() / grade_scandal_example()
# ---------------------------------------------------------------------------


class TestGradeDirectionExample:
    def test_correct_positive_call_passes(self) -> None:
        grade = grade_direction_example(
            name="test",
            expected_direction="positive",
            actual_score=0.4,
            actual_label="very_positive",
            actual_red_flags=[],
        )
        assert grade["overall_pass"] is True
        assert grade["direction_pass"] is True
        assert grade["no_false_alarm_pass"] is True

    def test_wrong_direction_fails(self) -> None:
        grade = grade_direction_example(
            name="test",
            expected_direction="positive",
            actual_score=-0.4,
            actual_label="very_negative",
            actual_red_flags=[],
        )
        assert grade["overall_pass"] is False
        assert grade["direction_pass"] is False
        assert "does not match" in grade["comment"]

    def test_correct_direction_but_spurious_flag_fails_overall(self) -> None:
        """
        A correct direction call with an unexpected red flag must still
        fail overall -- the "no false alarms" rubric row.
        """
        grade = grade_direction_example(
            name="test",
            expected_direction="positive",
            actual_score=0.3,
            actual_label="very_positive",
            actual_red_flags=["sebi mentioned in news coverage"],
        )
        assert grade["direction_pass"] is True
        assert grade["no_false_alarm_pass"] is False
        assert grade["overall_pass"] is False
        assert "unexpected red_flags" in grade["comment"]

    def test_passing_grade_has_pass_comment(self) -> None:
        grade = grade_direction_example(
            name="test",
            expected_direction="neutral",
            actual_score=0.0,
            actual_label="neutral",
            actual_red_flags=[],
        )
        assert grade["comment"] == "pass"


class TestGradeScandalExample:
    def test_detected_flag_passes(self) -> None:
        grade = grade_scandal_example(
            name="test",
            expected_flag_keywords=("sebi", "probe"),
            actual_red_flags=["sebi mentioned in news coverage"],
        )
        assert grade["overall_pass"] is True
        assert grade["red_flag_count"] == 1
        assert "sebi" in grade["matched_expected_keywords"]

    def test_no_flags_detected_is_a_hard_fail(self) -> None:
        grade = grade_scandal_example(
            name="test",
            expected_flag_keywords=("sebi",),
            actual_red_flags=[],
        )
        assert grade["overall_pass"] is False
        assert "hard fail" in grade["comment"]

    def test_unanticipated_but_valid_flag_still_passes(self) -> None:
        """
        A real scandal case may trip a different, equally-valid
        RED_FLAG_PHRASES entry than the ones anticipated at dataset-
        authoring time -- this must still count as detection working.
        """
        grade = grade_scandal_example(
            name="test",
            expected_flag_keywords=("sebi",),
            actual_red_flags=["fraud mentioned in news coverage"],
        )
        assert grade["overall_pass"] is True
        assert grade["matched_expected_keywords"] == ()


# ---------------------------------------------------------------------------
# 5 & 6. Aggregation functions
# ---------------------------------------------------------------------------


class TestDirectionAggregation:
    def _grade(self, overall_pass: bool) -> Any:
        return {
            "name": "x",
            "expected_direction": "positive",
            "actual_score": 0.3,
            "actual_label": "positive",
            "actual_red_flags": [],
            "direction_pass": overall_pass,
            "no_false_alarm_pass": True,
            "overall_pass": overall_pass,
            "comment": "pass" if overall_pass else "fail",
        }

    def test_nine_of_ten_is_90_percent(self) -> None:
        grades = [self._grade(True) for _ in range(9)] + [self._grade(False)]
        assert compute_direction_accuracy(grades) == 90.0

    def test_eight_of_ten_is_80_percent_and_does_not_meet_target(self) -> None:
        grades = [self._grade(True) for _ in range(8)] + [
            self._grade(False) for _ in range(2)
        ]
        accuracy = compute_direction_accuracy(grades)
        assert accuracy == 80.0
        # >80% is strict -- exactly 80% must not meet the target.
        assert meets_direction_target(accuracy) is False

    def test_empty_list_returns_zero_not_raises(self) -> None:
        assert compute_direction_accuracy([]) == 0.0

    def test_meets_direction_target_above_80(self) -> None:
        assert meets_direction_target(90.0) is True

    def test_accuracy_target_constant_is_80(self) -> None:
        assert DIRECTION_ACCURACY_TARGET_PCT == 80.0


class TestScandalAggregation:
    def _grade(self, overall_pass: bool) -> Any:
        return {
            "name": "x",
            "actual_red_flags": ["x"] if overall_pass else [],
            "red_flag_count": 1 if overall_pass else 0,
            "matched_expected_keywords": (),
            "overall_pass": overall_pass,
            "comment": "pass" if overall_pass else "fail",
        }

    def test_three_of_three_meets_target(self) -> None:
        grades = [self._grade(True) for _ in range(3)]
        passed, total = compute_scandal_detection(grades)
        assert (passed, total) == (3, 3)
        assert meets_scandal_target(passed, total) is True

    def test_two_of_three_does_not_meet_target(self) -> None:
        grades = [self._grade(True), self._grade(True), self._grade(False)]
        passed, total = compute_scandal_detection(grades)
        assert (passed, total) == (2, 3)
        assert meets_scandal_target(passed, total) is False

    def test_zero_total_does_not_meet_target(self) -> None:
        assert meets_scandal_target(0, 0) is False


# ---------------------------------------------------------------------------
# 7. sentiment_eval_target() -- deterministic, no mocking needed
# ---------------------------------------------------------------------------


class TestSentimentEvalTarget:
    def test_returns_expected_shape_for_positive_input(self) -> None:
        result = sentiment_eval_target(
            {
                "articles": [
                    {
                        "title": "Company wins record order",
                        "description": "Strong growth and robust expansion",
                    }
                ]
            }
        )
        assert result["sentiment_score"] > 0
        assert result["sentiment_label"] in ("positive", "very_positive")
        assert result["red_flags"] == []

    def test_missing_articles_key_returns_neutral_not_raises(self) -> None:
        result = sentiment_eval_target({})
        assert result["sentiment_score"] == 0.0
        assert result["sentiment_label"] == "neutral"

    def test_malformed_article_entries_are_skipped_not_raises(self) -> None:
        result = sentiment_eval_target({"articles": ["not-a-dict", 42, None]})
        assert result["sentiment_score"] == 0.0
        assert result["red_flags"] == []


# ---------------------------------------------------------------------------
# 8. LangSmith evaluator wrappers -- (run, example) -> dict
# ---------------------------------------------------------------------------


def _make_run(outputs: dict[str, Any]) -> Any:
    return SimpleNamespace(outputs=outputs, inputs={})


def _make_direction_example(name: str, expected_direction: str) -> Any:
    return SimpleNamespace(
        outputs={"name": name, "expected_direction": expected_direction}
    )


def _make_scandal_example(name: str, expected_flag_keywords: tuple[str, ...]) -> Any:
    return SimpleNamespace(
        outputs={"name": name, "expected_flag_keywords": expected_flag_keywords}
    )


class TestLangSmithEvaluatorWrappers:
    def test_direction_accuracy_evaluator_pass(self) -> None:
        run = _make_run(
            {"sentiment_score": 0.4, "sentiment_label": "positive", "red_flags": []}
        )
        example = _make_direction_example("x", "positive")
        result = direction_accuracy_evaluator(run, example)
        assert result["key"] == "directional_accuracy"
        assert result["score"] == 1

    def test_direction_accuracy_evaluator_fail(self) -> None:
        run = _make_run(
            {"sentiment_score": -0.4, "sentiment_label": "negative", "red_flags": []}
        )
        example = _make_direction_example("x", "positive")
        result = direction_accuracy_evaluator(run, example)
        assert result["score"] == 0

    def test_no_false_alarm_evaluator_pass(self) -> None:
        run = _make_run(
            {"sentiment_score": 0.4, "sentiment_label": "positive", "red_flags": []}
        )
        example = _make_direction_example("x", "positive")
        result = no_false_alarm_evaluator(run, example)
        assert result["key"] == "no_false_alarms"
        assert result["score"] == 1

    def test_no_false_alarm_evaluator_fail(self) -> None:
        run = _make_run(
            {
                "sentiment_score": 0.4,
                "sentiment_label": "positive",
                "red_flags": ["sebi mentioned in news coverage"],
            }
        )
        example = _make_direction_example("x", "positive")
        result = no_false_alarm_evaluator(run, example)
        assert result["score"] == 0

    def test_red_flag_detection_evaluator_pass(self) -> None:
        run = _make_run(
            {
                "sentiment_score": -0.3,
                "sentiment_label": "negative",
                "red_flags": ["sebi mentioned in news coverage"],
            }
        )
        example = _make_scandal_example("x", ("sebi",))
        result = red_flag_detection_evaluator(run, example)
        assert result["key"] == "red_flag_detection"
        assert result["score"] == 1

    def test_red_flag_detection_evaluator_fail(self) -> None:
        run = _make_run(
            {"sentiment_score": -0.1, "sentiment_label": "neutral", "red_flags": []}
        )
        example = _make_scandal_example("x", ("sebi",))
        result = red_flag_detection_evaluator(run, example)
        assert result["score"] == 0

    def test_evaluators_never_raise_on_malformed_run_outputs(self) -> None:
        run = SimpleNamespace(outputs="not-a-dict", inputs={})
        example = _make_direction_example("x", "positive")

        result = direction_accuracy_evaluator(run, example)
        assert result["score"] == 0

    def test_evaluators_never_raise_on_missing_outputs_attribute(self) -> None:
        run = SimpleNamespace(inputs={})  # no .outputs at all
        example = _make_scandal_example("x", ("sebi",))

        result = red_flag_detection_evaluator(run, example)
        assert result["score"] == 0


# ---------------------------------------------------------------------------
# 9. Full real dataset meets T-069's actual acceptance criteria
# ---------------------------------------------------------------------------


class TestFullDatasetMeetsTargets:
    """
    Runs the ENTIRE real dataset through the real, un-mocked grading
    pipeline and asserts T-069's literal acceptance criteria. Possible
    here (and not for T-068's Fundamental Analyst eval) specifically
    because sentiment scoring has no network/LLM dependency -- see
    backend/evals/sentiment_evaluators.py's module docstring.
    """

    def test_direction_dataset_meets_accuracy_target(self) -> None:
        grades = []
        for example in SENTIMENT_DIRECTION_DATASET:
            score, label, flags = score_news_set(example["articles"])
            grades.append(
                grade_direction_example(
                    name=example["name"],
                    expected_direction=example["expected_direction"],
                    actual_score=score,
                    actual_label=label,
                    actual_red_flags=flags,
                )
            )
        accuracy = compute_direction_accuracy(grades)
        failures = [g for g in grades if not g["overall_pass"]]
        assert meets_direction_target(accuracy), (
            f"Directional accuracy {accuracy}% does not exceed "
            f"{DIRECTION_ACCURACY_TARGET_PCT}%. Failures: {failures}"
        )

    def test_scandal_dataset_meets_detection_target(self) -> None:
        grades = []
        for example in SENTIMENT_SCANDAL_DATASET:
            _, _, flags = score_news_set(example["articles"])
            grades.append(
                grade_scandal_example(
                    name=example["name"],
                    expected_flag_keywords=example["expected_flag_keywords"],
                    actual_red_flags=flags,
                )
            )
        passed, total = compute_scandal_detection(grades)
        assert meets_scandal_target(passed, total), (
            f"Only {passed}/{total} scandal cases triggered a red flag "
            "-- T-069 requires 3-of-3."
        )

    @pytest.mark.parametrize(
        "example", SENTIMENT_DIRECTION_DATASET, ids=lambda ex: ex["name"]
    )
    def test_every_direction_example_individually_passes(self, example: Any) -> None:
        """
        Parametrized per-example so a CI failure names the exact example
        that broke, not just an aggregate percentage.
        """
        score, label, flags = score_news_set(example["articles"])
        grade = grade_direction_example(
            name=example["name"],
            expected_direction=example["expected_direction"],
            actual_score=score,
            actual_label=label,
            actual_red_flags=flags,
        )
        assert grade["overall_pass"], grade["comment"]

    @pytest.mark.parametrize(
        "example", SENTIMENT_SCANDAL_DATASET, ids=lambda ex: ex["name"]
    )
    def test_every_scandal_example_individually_passes(self, example: Any) -> None:
        _, _, flags = score_news_set(example["articles"])
        grade = grade_scandal_example(
            name=example["name"],
            expected_flag_keywords=example["expected_flag_keywords"],
            actual_red_flags=flags,
        )
        assert grade["overall_pass"], grade["comment"]
