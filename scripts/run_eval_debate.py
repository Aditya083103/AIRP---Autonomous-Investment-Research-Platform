# scripts/run_eval_debate.py
"""
AIRP -- Debate Quality LangSmith Eval Runner (T-070)

Runs the debate-quality eval designed in docs/EVAL_FRAMEWORK_DESIGN.md
§3.3 and implemented in backend/evals/debate_evaluators.py against the 5
synthetic post-debate snapshots in backend/evals/debate_eval_dataset.py.

Like scripts/run_eval_sentiment.py (T-069) and unlike
scripts/run_eval_fundamental.py (T-068), grading here needs NO network
access and NO real LLM call -- the eval grades already-produced state
(a ContrarianReport / debate_rounds / InvestmentDecision snapshot), not
a live agent call. That means this script:
  1. Always produces the SAME result on every run.
  2. Still prints the same style of pass/fail report as the other eval
     runners for a consistent PR-evidence format.
  3. Still ALSO pushes to LangSmith (best-effort, when LANGSMITH_API_KEY
     is configured) for dashboard/observability consistency with every
     other AIRP eval, per EVAL_FRAMEWORK_DESIGN.md §4's shared naming
     convention.

The equivalent CI-covered assertions (that this dataset actually meets
T-070's acceptance criteria) live directly in
backend/tests/unit/test_debate_evaluators.py's
TestFullDatasetMeetsTargets -- since this eval needs no live external
call, that pytest suite is the actual proof, and this script is mainly
useful for the human-readable report and the optional LangSmith push.

Usage
-----
    set ENVIRONMENT=development   (Windows CMD; do NOT chain with &&)
    python -m scripts.run_eval_debate

Requirements
------------
- None strictly required -- this script runs fully offline by default.
- Optional: LANGSMITH_API_KEY set, to also push results to LangSmith.

Design decisions
-----------------
* NO ``from __future__ import annotations`` -- AIRP rule.
* Mirrors the structure of scripts/run_eval_sentiment.py for a
  consistent report format across every AIRP eval runner.
"""

import os

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "development")

import sys  # noqa: E402
from typing import Any  # noqa: E402

from backend.config import settings  # noqa: E402
from backend.evals.debate_eval_dataset import DEBATE_EVAL_DATASET  # noqa: E402
from backend.evals.debate_evaluators import (  # noqa: E402
    DebateGrade,
    compute_pass_rate,
    contrarian_disagrees_evaluator,
    debate_eval_target,
    grade_debate_snapshot,
    meets_debate_quality_target,
    multi_agent_engagement_evaluator,
    novelty_evaluator,
    pm_engages_with_debate_evaluator,
)

LANGSMITH_DATASET_NAME = "airp-eval-debate-quality"


def _run_grading() -> list[DebateGrade]:
    """Grade every post-debate snapshot in the dataset."""
    grades: list[DebateGrade] = []
    print(f"\n{'=' * 78}")
    print("AIRP -- Debate Quality Eval (T-070)")
    print(f"{'=' * 78}\n")

    for example in DEBATE_EVAL_DATASET:
        grade = grade_debate_snapshot(
            name=example["name"],
            contrarian=example["contrarian"],
            debate_rounds=example["debate_rounds"],
            decision=example["decision"],
        )
        grades.append(grade)
        status = "PASS" if grade["overall_pass"] else "FAIL"
        print(f"{status}  {example['name']}")
        print(
            f"       contrarian_disagrees={grade['contrarian_disagrees_pass']}  "
            f"multi_agent_engagement={grade['multi_agent_engagement_pass']}  "
            f"novelty={grade['novelty_pass']}  "
            f"pm_engages_with_debate={grade['pm_engages_with_debate_pass']}"
        )
        if not grade["overall_pass"]:
            print(f"       -> {grade['comment']}")

    return grades


def _print_summary(grades: list[DebateGrade]) -> bool:
    """Print the pass-rate summary; return whether the target is met."""
    passed, total = compute_pass_rate(grades)
    target_met = meets_debate_quality_target(passed, total)

    print(f"\n{'-' * 78}")
    print(
        f"Snapshots passing all 4 checks: {passed}/{total} -- "
        f"{'MEETS TARGET (all-or-nothing)' if target_met else 'BELOW TARGET'}"
    )
    print(f"{'=' * 78}\n")
    return target_met


def _push_to_langsmith() -> None:
    """
    Best-effort: upload the dataset and run a LangSmith experiment.

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

        existing_datasets = list(
            client.list_datasets(dataset_name=LANGSMITH_DATASET_NAME)
        )
        if existing_datasets:
            dataset = existing_datasets[0]
            print(f"Reusing existing LangSmith dataset '{LANGSMITH_DATASET_NAME}'")
        else:
            dataset = client.create_dataset(
                dataset_name=LANGSMITH_DATASET_NAME,
                description=(
                    "AIRP debate-quality eval -- 5 synthetic post-debate "
                    "snapshots. See docs/EVAL_FRAMEWORK_DESIGN.md §3.3 "
                    "and backend/evals/debate_eval_dataset.py."
                ),
            )
            print(f"Created LangSmith dataset '{LANGSMITH_DATASET_NAME}'")

        existing_examples: list[Any] = list(
            client.list_examples(dataset_id=dataset.id)
        )
        if not existing_examples:
            for example in DEBATE_EVAL_DATASET:
                client.create_example(
                    inputs={
                        "name": example["name"],
                        "contrarian": example["contrarian"],
                        "debate_rounds": list(example["debate_rounds"]),
                        "decision": example["decision"],
                    },
                    outputs={},
                    dataset_id=dataset.id,
                )
            print(f"Uploaded {len(DEBATE_EVAL_DATASET)} examples to LangSmith")
        else:
            print(
                f"Dataset already has {len(existing_examples)} examples -- "
                "skipping re-upload"
            )

        print("Running LangSmith experiment...")
        results = langsmith_evaluate(
            debate_eval_target,
            data=LANGSMITH_DATASET_NAME,
            evaluators=[
                contrarian_disagrees_evaluator,
                multi_agent_engagement_evaluator,
                novelty_evaluator,
                pm_engages_with_debate_evaluator,
            ],
            experiment_prefix="debate-quality-eval",
            metadata={"task": "T-070"},
        )
        print(f"LangSmith experiment complete: {results}")
        print(
            "View the run in the LangSmith dashboard under project "
            f"'{settings.langchain_project}'.\n"
        )
    except Exception as exc:  # never let LangSmith issues kill the script
        print(f"LangSmith push failed (non-fatal): {exc}\n")


def main() -> int:
    grades = _run_grading()
    target_met = _print_summary(grades)
    _push_to_langsmith()
    return 0 if target_met else 1


if __name__ == "__main__":
    sys.exit(main())