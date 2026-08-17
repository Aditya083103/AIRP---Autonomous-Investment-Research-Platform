# scripts/run_eval_fundamental.py
"""
AIRP -- Fundamental Analyst LangSmith Eval Runner (T-068)

Runs the Fundamental Analyst eval designed in docs/EVAL_FRAMEWORK_DESIGN.md
§3.1 and implemented in backend/evals/fundamental_evaluators.py against the
5-company dataset in backend/evals/fundamental_eval_dataset.py.

This is a manual, one-off script (see scripts/README.md) -- NOT part of the
pytest/CI gate. It:
  1. Calls the REAL Fundamental Analyst core logic (real yFinance / Alpha
     Vantage fetches, real LLM call) for all 5 dataset companies.
  2. Grades every result against ground truth using the pure, CI-tested
     grading logic in backend/evals/fundamental_evaluators.py.
  3. Prints a pass/fail table and the overall accuracy vs. the >70% target
     (T-068's acceptance criterion) to the console -- this works even
     without a LangSmith key configured, so the eval is runnable standalone.
  4. When LANGSMITH_API_KEY is configured (tracing_enabled), ALSO uploads
     the dataset to LangSmith (idempotent -- reuses the dataset if it
     already exists) and runs the same evaluators through
     ``langsmith.evaluate()`` so a real experiment lands in the LangSmith
     dashboard -- satisfying "results in LangSmith" per the task
     description. When no key is configured, this step is skipped with a
     clear console message rather than failing the whole script.

Usage
-----
    set ENVIRONMENT=development   (Windows CMD; do NOT chain with &&)
    python -m scripts.run_eval_fundamental

Requirements
------------
- A real LLM key configured in .env (LLM_PROVIDER=groq + GROQ_API_KEY is
  the default AIRP dev provider; LLM_PROVIDER=anthropic works too).
- Network access to yFinance / Alpha Vantage for real financials/ratios.
- Optional: LANGSMITH_API_KEY set, to also push results to LangSmith.
- Makes REAL calls -- not a unit test, not mocked, not run in CI. Costs a
  handful of LLM requests and, if configured, a LangSmith experiment.

Design decisions
-----------------
* NO ``from __future__ import annotations`` -- AIRP rule.
* Mirrors the structure of scripts/manual_qa_chat_personalization.py: a
  fixed, documented, human-readable console report a PR description can
  paste directly, not a silent pass/fail exit code.
* The LangSmith upload step is deliberately best-effort and never fails
  the script -- an eval run should still report local pass/fail even if
  the LangSmith account/network is unavailable, matching the "results in
  LangSmith" criterion being additive evidence, not the sole output.
"""

import os

# ENVIRONMENT must be set before any backend module is imported.
os.environ.setdefault("ENVIRONMENT", "development")

import sys  # noqa: E402
from typing import Any  # noqa: E402

from backend.config import settings  # noqa: E402
from backend.evals.fundamental_eval_dataset import (  # noqa: E402
    FUNDAMENTAL_EVAL_DATASET,
)
from backend.evals.fundamental_evaluators import (  # noqa: E402
    ACCURACY_TARGET_PCT,
    FundamentalGrade,
    compute_accuracy,
    directional_accuracy_evaluator,
    fundamental_eval_target,
    grade_fundamental_output,
    honest_abstention_evaluator,
    meets_target,
    schema_validity_evaluator,
)

LANGSMITH_DATASET_NAME = "airp-eval-fundamental"


def _run_local_grading() -> list[FundamentalGrade]:
    """
    Call the real agent for every dataset example and grade the result.

    Prints a per-company line as it goes so a long-running real-data run
    shows progress rather than sitting silent.
    """
    grades: list[FundamentalGrade] = []
    print(f"\n{'=' * 70}")
    print("AIRP -- Fundamental Analyst Eval (T-068)")
    print(f"{'=' * 70}\n")

    for example in FUNDAMENTAL_EVAL_DATASET:
        ticker = example["ticker"]
        print(f"Running: {example['company_name']} ({ticker}) ...", end=" ", flush=True)
        output = fundamental_eval_target(
            {"company_name": example["company_name"], "ticker": ticker}
        )
        grade = grade_fundamental_output(
            ticker=ticker,
            expected_bucket=example["expected_bucket"],
            actual_score=output.get("score"),
            actual_data_quality=str(output.get("data_quality", "insufficient")),
            actual_error=output.get("error"),
        )
        grades.append(grade)
        status = "PASS" if grade["overall_pass"] else "FAIL"
        print(f"{status} (score={grade['actual_score']!r})")

    return grades


def _print_report(grades: list[FundamentalGrade]) -> float:
    """Print the pass/fail table and overall accuracy; return accuracy %."""
    print(f"\n{'-' * 70}")
    print(
        f"{'Ticker':<24}{'Expected':<14}{'Score':<8}"
        f"{'Directional':<13}{'Abstention':<12}{'Schema':<8}{'Overall'}"
    )
    print(f"{'-' * 70}")
    for g in grades:
        print(
            f"{g['ticker']:<24}{g['expected_bucket']:<14}"
            f"{str(g['actual_score']):<8}"
            f"{'PASS' if g['directional_pass'] else 'FAIL':<13}"
            f"{'PASS' if g['abstention_pass'] else 'FAIL':<12}"
            f"{'PASS' if g['schema_pass'] else 'FAIL':<8}"
            f"{'PASS' if g['overall_pass'] else 'FAIL'}"
        )
        if not g["overall_pass"]:
            print(f"    -> {g['comment']}")

    accuracy = compute_accuracy(grades)
    target_met = meets_target(accuracy)
    print(f"{'-' * 70}")
    print(
        f"Overall accuracy: {accuracy}% "
        f"(target: >{ACCURACY_TARGET_PCT}%) -- "
        f"{'MEETS TARGET' if target_met else 'BELOW TARGET'}"
    )
    print(f"{'=' * 70}\n")
    return accuracy


def _push_to_langsmith() -> None:
    """
    Best-effort: upload the dataset and run a LangSmith experiment.

    Skips cleanly (with a console message) when tracing is not
    configured. Never raises -- a LangSmith account hiccup should not
    take down the whole eval run, since the local grading report above
    has already been printed by the time this runs.
    """
    if not settings.tracing_enabled:
        print(
            "LANGSMITH_API_KEY not configured -- skipping LangSmith "
            "dataset upload and experiment run. Local grading above is "
            "still the authoritative result for this run.\n"
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
                    "AIRP Fundamental Analyst eval -- 5 companies with "
                    "known fundamental-quality buckets. See "
                    "docs/EVAL_FRAMEWORK_DESIGN.md §3.1 and "
                    "backend/evals/fundamental_eval_dataset.py."
                ),
            )
            print(f"Created LangSmith dataset '{LANGSMITH_DATASET_NAME}'")

        existing_examples: list[Any] = list(client.list_examples(dataset_id=dataset.id))

        if not existing_examples:
            for example in FUNDAMENTAL_EVAL_DATASET:
                client.create_example(
                    inputs={
                        "company_name": example["company_name"],
                        "ticker": example["ticker"],
                    },
                    outputs={"expected_bucket": example["expected_bucket"]},
                    dataset_id=dataset.id,
                )
            print(f"Uploaded {len(FUNDAMENTAL_EVAL_DATASET)} examples to LangSmith")
        else:
            print(
                f"Dataset already has {len(existing_examples)} examples -- "
                "skipping re-upload"
            )

        print("Running LangSmith experiment (this makes real LLM calls)...")
        results = langsmith_evaluate(
            fundamental_eval_target,
            data=LANGSMITH_DATASET_NAME,
            evaluators=[
                directional_accuracy_evaluator,
                honest_abstention_evaluator,
                schema_validity_evaluator,
            ],
            experiment_prefix="fundamental-eval",
            metadata={"task": "T-068"},
        )
        print(f"LangSmith experiment complete: {results}")
        print(
            "View the run in the LangSmith dashboard under project "
            f"'{settings.langchain_project}'.\n"
        )
    except Exception as exc:  # never let LangSmith issues kill the script
        print(f"LangSmith push failed (non-fatal): {exc}\n")


def main() -> int:
    grades = _run_local_grading()
    accuracy = _print_report(grades)
    _push_to_langsmith()
    return 0 if meets_target(accuracy) else 1


if __name__ == "__main__":
    sys.exit(main())