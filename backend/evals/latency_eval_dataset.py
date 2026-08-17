# backend/evals/latency_eval_dataset.py
"""
AIRP -- End-to-End Latency Eval Dataset (T-071)

Fixed 3-company dataset for the latency benchmark designed in T-067's
docs/EVAL_FRAMEWORK_DESIGN.md and implemented here per T-071's acceptance
criteria: "Time full pipeline for 3 companies; assert <90s p50, <120s p95;
log per-node latency breakdown".

Unlike the accuracy-style evals (fundamental / sentiment / debate), this
dataset carries no ground-truth expected output -- there is nothing to
grade a verdict against. Each row is simply a real NSE-listed company for
scripts/run_eval_latency.py to run the REAL end-to-end pipeline against,
chosen to span three different sectors so the benchmark is not
accidentally flattering one agent's happy path (e.g. Technical Analyst's
OHLCV fetch behaves differently for a thinly-traded vs. heavily-traded
stock; Macro Economist's sector-tailwind lookup differs by sector).

Company selection rationale
----------------------------
* Tata Consultancy Services (TCS.NS) -- IT Services. Reuses the exact
  ticker already exercised by scripts/run_full_analysis.py, so any
  latency regression here is directly comparable to that script's prior
  manual runs.
* Infosys (INFY.NS) -- IT Services peer to TCS, reuses the ticker from
  scripts/run_full_analysis_infosys.py. Included specifically because
  it is a second, independent full run of the SAME sector -- this
  isolates whether latency variance comes from sector-specific data
  (e.g. Screener.in peer-comparison set size) or is just general
  pipeline noise.
* Reliance Industries (RELIANCE.NS) -- Energy / Conglomerate, the
  deliberate sector outlier of the three. Reliance's much larger and
  more heterogeneous financial statements (multiple business segments:
  refining, retail, telecom, digital) make it a reasonable stress case
  for the Fundamental Analyst and Valuation Agent's peer-comparison
  logic versus the two single-segment IT majors.

Public interface
-----------------
    LatencyEvalCompany       -- TypedDict: one dataset row
    LATENCY_EVAL_COMPANIES   -- tuple[LatencyEvalCompany, ...] -- all 3 rows

Usage
-----
    from backend.evals.latency_eval_dataset import LATENCY_EVAL_COMPANIES

    for company in LATENCY_EVAL_COMPANIES:
        ...  # run the real pipeline against company["ticker"]
"""

from typing import TypedDict

# ---------------------------------------------------------------------------
# Dataset row shape
# ---------------------------------------------------------------------------


class LatencyEvalCompany(TypedDict):
    """One company the latency benchmark runs the full pipeline against."""

    company_name: str
    ticker: str
    exchange: str
    sector: str
    raw_query: str


# ---------------------------------------------------------------------------
# The 3-company dataset (T-071's literal acceptance criterion: "3 companies")
# ---------------------------------------------------------------------------

LATENCY_EVAL_COMPANIES: tuple[LatencyEvalCompany, ...] = (
    {
        "company_name": "Tata Consultancy Services",
        "ticker": "TCS.NS",
        "exchange": "NSE",
        "sector": "Information Technology",
        "raw_query": "Should I invest in TCS?",
    },
    {
        "company_name": "Infosys",
        "ticker": "INFY.NS",
        "exchange": "NSE",
        "sector": "Information Technology",
        "raw_query": "Should I invest in Infosys?",
    },
    {
        "company_name": "Reliance Industries",
        "ticker": "RELIANCE.NS",
        "exchange": "NSE",
        "sector": "Energy / Conglomerate",
        "raw_query": "Should I invest in Reliance Industries?",
    },
)


__all__ = [
    "LatencyEvalCompany",
    "LATENCY_EVAL_COMPANIES",
]
