# scripts/run_eval_sentiment.py
"""
AIRP -- News Sentiment Agent LangSmith Eval Runner (T-069)

Runs the Sentiment Agent eval designed in docs/EVAL_FRAMEWORK_DESIGN.md
§3.2 and implemented in backend/evals/sentiment_evaluators.py against the
10 directional test news sets and 3 known-scandal cases in
backend/evals/sentiment_eval_dataset.py.

Unlike scripts/run_eval_fundamental.py (T-068), grading here needs NO
network access and NO real LLM call -- sentiment_score, sentiment_label,
and (keyword-detected) red_flags are all pure, deterministic functions of
the article text (see backend/evals/sentiment_evaluators.py's module
docstring). That means this script:
  1. Always produces the SAME result on every run (no flakiness, no
     dependency on live news data, no LLM quota consumed).
  2. Still prints the same style of pass/fail report as
     run_eval_fundamental.py for a consistent PR-evidence format.
  3. Still ALSO pushes to LangSmith (best-effort, when LANGSMITH_API_KEY
     is configured) purely for dashboard/observability consistency with
     every other AIRP eval, per EVAL_FRAMEWORK_DESIGN.md §4's shared
     naming convention -- this step is optional evidence, not required
     for the eval's own correctness the way it effectively was for
     T-068's real-data run.

This is still a manual, one-off script (see scripts/README.md) rather
than a pytest test, so its console report matches the project's other
eval runner scripts. The equivalent CI-covered assertions (that this
dataset actually meets the >80% / 3-of-3 targets) live directly in
backend/tests/unit/test_sentiment_evaluators.py's
TestFullDatasetMeetsTargets -- since this eval needs no live external
call, that pytest suite doubles as the actual proof, and this script is
mainly useful for the human-readable report and the optional LangSmith
push.

Usage
-----
    set ENVIRONMENT=development   (Windows CMD; do NOT chain with &&)
    python -m scripts.run_eval_sentiment

Requirements
------------
- None strictly required -- this script runs fully offline by default.
- Optional: LANGSMITH_API_KEY set, to also push results to LangSmith.

Design decisions
-----------------
* NO ``from __future__ import annotations`` -- AIRP rule.
* Mirrors the structure of scripts/run_eval_fundamental.py for a
  consistent report format across every AIRP eval runner.
"""

import os

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "development")

import sys  # noqa: E402
from typing import Any  # noqa: E402

from backend.config import settings  # noqa: E402
from backend.evals.sentiment_eval_dataset import (  # noqa: E402
    SENTIMENT_DIRECTION_DATASET,
    SENTIMENT_SCANDAL_DATASET,
)
from backend.evals.sentiment_evaluators import (  # noqa: E402
    DIRECTION_ACCURACY_TARGET_PCT,
    DirectionGrade,
    ScandalGrade,
    compute_direction_accuracy,
    compute_scandal_detection,
    direction_accuracy_evaluator,
    grade_direction_example,
    grade_scandal_example,
    meets_direction_target,
    meets_scandal_target,
    no_false_alarm_evaluator,
    red_flag_detection_evaluator,
    score_news_set,
    sentiment_eval_target,
)

LANGSMITH_DIRECTION_DATASET_NAME = "airp-eval-sentiment-direction"
LANGSMITH_SCANDAL_DATASET_NAME = "airp-eval-sentiment-scandal"


def _run_direction_grading() -> list[DirectionGrade]:
    """Grade every directional test news set."""
    grades: list[DirectionGrade] = []
    print(f"\n{'=' * 78}")
    print("AIRP -- Sentiment Agent Eval: Directional Accuracy (T-069)")
    print(f"{'=' * 78}\n")

    for example in SENTIMENT_DIRECTION_DATASET:
        score, label, flags = score_news_set(example["articles"])
        grade = grade_direction_example(
            name=example["name"],
            expected_direction=example["expected_direction"],
            actual_score=score,
            actual_label=label,
            actual_red_flags=flags,
        )
        grades.append(grade)
        status = "PASS" if grade["overall_pass"] else "FAIL"
        print(f"{status}  {example['name']:<32} score={score:+.4f} label={label}")
        if not grade["overall_pass"]:
            print(f"       -> {grade['comment']}")

    return grades


def _run_scandal_grading() -> list[ScandalGrade]:
    """Grade every known-scandal test case."""
    grades: list[ScandalGrade] = []
    print(f"\n{'=' * 78}")
    print("AIRP -- Sentiment Agent Eval: Red-Flag Detection (T-069)")
    print(f"{'=' * 78}\n")

    for example in SENTIMENT_SCANDAL_DATASET:
        _, _, flags = score_news_set(example["articles"])
        grade = grade_scandal_example(
            name=example["name"],
            expected_flag_keywords=example["expected_flag_keywords"],
            actual_red_flags=flags,
        )
        grades.append(grade)
        status = "PASS" if grade["overall_pass"] else "FAIL"
        print(f"{status}  {example['name']:<32} flags={grade['red_flag_count']}")
        for flag in grade["actual_red_flags"]:
            print(f"       - {flag}")
        if not grade["overall_pass"]:
            print(f"       -> {grade['comment']}")

    return grades


def _print_summary(
    direction_grades: list[DirectionGrade], scandal_grades: list[ScandalGrade]
) -> tuple[float, bool]:
    """Print the overall accuracy/detection summary; return (accuracy, all_pass)."""
    accuracy = compute_direction_accuracy(direction_grades)
    direction_ok = meets_direction_target(accuracy)

    scandal_passed, scandal_total = compute_scandal_detection(scandal_grades)
    scandal_ok = meets_scandal_target(scandal_passed, scandal_total)

    print(f"\n{'-' * 78}")
    print(
        f"Directional accuracy: {accuracy}% "
        f"(target: >{DIRECTION_ACCURACY_TARGET_PCT}%) -- "
        f"{'MEETS TARGET' if direction_ok else 'BELOW TARGET'}"
    )
    print(
        f"Red-flag detection:   {scandal_passed}/{scandal_total} scandal cases "
        f"detected -- {'MEETS TARGET (3-of-3)' if scandal_ok else 'BELOW TARGET'}"
    )
    print(f"{'=' * 78}\n")

    return accuracy, direction_ok and scandal_ok


def _push_to_langsmith() -> None:
    """
    Best-effort: upload both datasets and run LangSmith experiments.

    Skips cleanly when tracing is not configured. Never raises -- see
    run_eval_fundamental.py's identical rationale for why this is
    best-effort rather than blocking.
    """
    if not settings.tracing_enabled:
        print(
            "LANGSMITH_API_KEY not configured -- skipping LangSmith "
            "dataset upload and experiment run. The local grading above "
            "is still the authoritative result for this run.\n"
        )
        return

    try:
        from langsmith import Client
        from langsmith import evaluate as langsmith_evaluate

        client = Client()

        _upload_dataset_if_missing(
            client,
            LANGSMITH_DIRECTION_DATASET_NAME,
            "AIRP Sentiment Agent eval -- 10 directional test news sets. "
            "See docs/EVAL_FRAMEWORK_DESIGN.md §3.2 and "
            "backend/evals/sentiment_eval_dataset.py.",
            [
                {
                    "inputs": {"articles": list(ex["articles"])},
                    "outputs": {
                        "name": ex["name"],
                        "expected_direction": ex["expected_direction"],
                    },
                }
                for ex in SENTIMENT_DIRECTION_DATASET
            ],
        )
        print("Running LangSmith experiment: directional accuracy...")
        direction_results = langsmith_evaluate(
            sentiment_eval_target,
            data=LANGSMITH_DIRECTION_DATASET_NAME,
            evaluators=[direction_accuracy_evaluator, no_false_alarm_evaluator],
            experiment_prefix="sentiment-eval-direction",
            metadata={"task": "T-069"},
        )
        print(f"Direction experiment complete: {direction_results}")

        _upload_dataset_if_missing(
            client,
            LANGSMITH_SCANDAL_DATASET_NAME,
            "AIRP Sentiment Agent eval -- 3 known-scandal red-flag "
            "detection cases. See docs/EVAL_FRAMEWORK_DESIGN.md §3.2 and "
            "backend/evals/sentiment_eval_dataset.py.",
            [
                {
                    "inputs": {"articles": list(ex["articles"])},
                    "outputs": {
                        "name": ex["name"],
                        "expected_flag_keywords": list(ex["expected_flag_keywords"]),
                    },
                }
                for ex in SENTIMENT_SCANDAL_DATASET
            ],
        )
        print("Running LangSmith experiment: red-flag detection...")
        scandal_results = langsmith_evaluate(
            sentiment_eval_target,
            data=LANGSMITH_SCANDAL_DATASET_NAME,
            evaluators=[red_flag_detection_evaluator],
            experiment_prefix="sentiment-eval-scandal",
            metadata={"task": "T-069"},
        )
        print(f"Scandal experiment complete: {scandal_results}")
        print(
            "View both runs in the LangSmith dashboard under project "
            f"'{settings.langchain_project}'.\n"
        )
    except Exception as exc:  # never let LangSmith issues kill the script
        print(f"LangSmith push failed (non-fatal): {exc}\n")


def _upload_dataset_if_missing(
    client: Any,
    dataset_name: str,
    description: str,
    examples: list[dict[str, Any]],
) -> None:
    """Create the named LangSmith dataset + examples if not already present."""
    existing_datasets = list(client.list_datasets(dataset_name=dataset_name))
    if existing_datasets:
        dataset = existing_datasets[0]
        print(f"Reusing existing LangSmith dataset '{dataset_name}'")
    else:
        dataset = client.create_dataset(
            dataset_name=dataset_name, description=description
        )
        print(f"Created LangSmith dataset '{dataset_name}'")

    existing_examples = list(client.list_examples(dataset_id=dataset.id))
    if existing_examples:
        print(
            f"Dataset '{dataset_name}' already has {len(existing_examples)} "
            "examples -- skipping re-upload"
        )
        return

    for example in examples:
        client.create_example(
            inputs=example["inputs"],
            outputs=example["outputs"],
            dataset_id=dataset.id,
        )
    print(f"Uploaded {len(examples)} examples to '{dataset_name}'")


def main() -> int:
    direction_grades = _run_direction_grading()
    scandal_grades = _run_scandal_grading()
    _accuracy, all_pass = _print_summary(direction_grades, scandal_grades)
    _push_to_langsmith()
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())