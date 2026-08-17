# backend/evals/fundamental_eval_dataset.py
"""
AIRP -- Fundamental Analyst LangSmith Eval Dataset (T-068)

Ground-truth dataset for the Fundamental Analyst eval, built per the design
in docs/EVAL_FRAMEWORK_DESIGN.md §3.1: 5 companies spanning a deliberate
fundamental-quality spread (2 strong, 1 neutral, 1 weak, 1 deliberately
insufficient-data), so the eval cannot pass by always guessing "medium".

Ground truth is fixed at dataset-authoring time (below) and is NOT
re-derived from live data at eval time -- this keeps the eval stable even
if a company's live financials move between runs, exactly as
EVAL_FRAMEWORK_DESIGN.md §3.1 specifies.

IMPORTANT -- ground truth is a starting point, not a permanent oracle.
The four real tickers below are large, extremely well-documented public
companies chosen specifically because their bucket assignment is not a
close call (a dominant low-debt IT exporter, a high-ROE FMCG major, a
known heavily-leveraged distressed telecom, and a solid-but-unremarkable
IT services peer). Re-confirm each bucket against current Screener.in /
analyst-consensus data before relying on eval results for anything beyond
smoke-testing the framework itself -- fundamentals do genuinely change
over multi-year horizons, and this file is not on any schedule that
re-verifies them.

Public interface
-----------------
    FundamentalEvalExample  -- TypedDict: one dataset row
    FUNDAMENTAL_EVAL_DATASET -- tuple[FundamentalEvalExample, ...] -- all 5 rows

Usage
-----
    from backend.evals.fundamental_eval_dataset import FUNDAMENTAL_EVAL_DATASET

    for example in FUNDAMENTAL_EVAL_DATASET:
        ...  # run the agent against example["ticker"], grade vs
             # example["expected_bucket"]
"""

from typing import Literal, TypedDict

# ---------------------------------------------------------------------------
# Bucket type -- must match the keys used in fundamental_evaluators.py
# ---------------------------------------------------------------------------

FundamentalBucket = Literal["strong", "neutral", "weak", "insufficient"]


class FundamentalEvalExample(TypedDict):
    """One row of the Fundamental Analyst eval dataset."""

    company_name: str
    ticker: str
    expected_bucket: FundamentalBucket
    rationale: str


# ---------------------------------------------------------------------------
# The 5-company dataset
# ---------------------------------------------------------------------------

FUNDAMENTAL_EVAL_DATASET: tuple[FundamentalEvalExample, ...] = (
    {
        "company_name": "Tata Consultancy Services",
        "ticker": "TCS.NS",
        "expected_bucket": "strong",
        "rationale": (
            "India's largest IT services exporter -- consistently high "
            "operating margins (~24%), low leverage, strong FCF "
            "generation over many consecutive years. Should score high "
            "on revenue quality, margins, and balance-sheet safety."
        ),
    },
    {
        "company_name": "Hindustan Unilever",
        "ticker": "HINDUNILVR.NS",
        "expected_bucket": "strong",
        "rationale": (
            "Dominant FMCG major -- high ROE, low net debt, stable "
            "double-digit net margins. Included alongside TCS "
            "specifically to check the agent scores high consistently "
            "across a different sector, not just IT."
        ),
    },
    {
        "company_name": "Wipro",
        "ticker": "WIPRO.NS",
        "expected_bucket": "neutral",
        "rationale": (
            "A solid, profitable IT services company, but a well-known "
            "growth-and-margin laggard relative to TCS/Infosys over "
            "recent years. Tests that the agent doesn't reflexively "
            "score every large IT name in the 'strong' bucket."
        ),
    },
    {
        "company_name": "Vodafone Idea",
        "ticker": "IDEA.NS",
        "expected_bucket": "weak",
        "rationale": (
            "Heavily leveraged, cash-flow-negative telecom operator "
            "with a well-documented negative net worth and large AGR- "
            "dues liability. An unambiguous 'weak' case -- checks the "
            "agent isn't reflexively positive on a large, well-known "
            "name."
        ),
    },
    {
        "company_name": "AIRP Eval Placeholder Co",
        "ticker": "AIRPEVALPLACEHOLDER.NS",
        "expected_bucket": "insufficient",
        "rationale": (
            "Deliberately not a real ticker. A genuinely thin-data "
            "small/micro-cap is not a *stable* test case -- more data "
            "can appear for a real company between eval runs, silently "
            "breaking this row. An intentionally invalid ticker "
            "deterministically forces fetch_financials/fetch_ratios "
            "into their documented empty-result path on every run, "
            "which is exactly what this row exists to check: does the "
            "agent honestly report score=None / "
            "data_quality='insufficient' rather than fabricate a "
            "number."
        ),
    },
)

__all__ = [
    "FundamentalBucket",
    "FundamentalEvalExample",
    "FUNDAMENTAL_EVAL_DATASET",
]
