# backend/evals/sentiment_eval_dataset.py
"""
AIRP -- News Sentiment Agent LangSmith Eval Dataset (T-069)

Ground-truth dataset for the Sentiment Agent eval, built per the design in
docs/EVAL_FRAMEWORK_DESIGN.md §3.2: 10 directional test news sets (4
clearly positive, 4 clearly negative, 2 genuinely mixed/flat) plus 3
known-scandal cases held out specifically for the red-flag detection
check.

Unlike the Fundamental Analyst eval (T-068), which had to call a real
ticker's live financials, this dataset does NOT reference any real
company or ticker. The Sentiment Agent's sentiment_score, sentiment_label,
and (keyword-detected) red_flags are all computed by pure, deterministic
functions in backend/agents/sentiment_analyst.py --
_score_article / _aggregate_scores / _label_from_score / _detect_red_flags
-- BEFORE any LLM call happens (the LLM only synthesises narrative
afterwards: top headlines, dominant topics, summary). So every example
here is a synthetic (title, description) article pair, engineered against
the agent's own real keyword lists (POSITIVE_KEYWORDS, NEGATIVE_KEYWORDS,
RED_FLAG_PHRASES) so its expected outcome is fully deterministic and
reproducible -- no network call, no LLM call, no flakiness.

Every example is checked against the real keyword lists at test-build
time (see backend/tests/unit/test_sentiment_evaluators.py's
TestDatasetShape class), not just by hand -- so if
POSITIVE_KEYWORDS/NEGATIVE_KEYWORDS/RED_FLAG_PHRASES ever change in
sentiment_analyst.py, a broken assumption here surfaces as a failing
CI test rather than a silently-wrong eval.

Public interface
-----------------
    ArticleInput                    -- TypedDict: one synthetic article
    SentimentDirectionExample       -- TypedDict: one directional test set
    SentimentScandalExample         -- TypedDict: one scandal test set
    SENTIMENT_DIRECTION_DATASET     -- tuple[..., ...] -- the 10 direction sets
    SENTIMENT_SCANDAL_DATASET       -- tuple[..., ...] -- the 3 scandal sets

Usage
-----
    from backend.evals.sentiment_eval_dataset import (
        SENTIMENT_DIRECTION_DATASET,
        SENTIMENT_SCANDAL_DATASET,
    )

    for example in SENTIMENT_DIRECTION_DATASET:
        ...  # score example["articles"], grade vs example["expected_direction"]
"""

from typing import Literal, TypedDict

# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------

SentimentDirection = Literal["positive", "negative", "neutral"]


class ArticleInput(TypedDict):
    """One synthetic news article -- matches the shape fetch_news returns."""

    title: str
    description: str


class SentimentDirectionExample(TypedDict):
    """One directional test news set."""

    name: str
    articles: tuple[ArticleInput, ...]
    expected_direction: SentimentDirection
    rationale: str


class SentimentScandalExample(TypedDict):
    """One known-scandal test case, held out for the red-flag check."""

    name: str
    articles: tuple[ArticleInput, ...]
    expected_flag_keywords: tuple[str, ...]
    rationale: str


# ---------------------------------------------------------------------------
# 10 directional test news sets -- 4 positive, 4 negative, 2 neutral/mixed
# ---------------------------------------------------------------------------
#
# Every article below is deliberately built from exact substrings of
# sentiment_analyst.py's own POSITIVE_KEYWORDS / NEGATIVE_KEYWORDS lists
# (case-insensitive substring matching, same as _score_article itself
# uses) and deliberately AVOIDS every RED_FLAG_PHRASES substring, so none
# of these 10 sets should ever populate red_flags -- that absence is
# itself part of what TestDatasetShape / test_sentiment_evaluators.py
# verifies (the "no false alarms" rubric row in
# EVAL_FRAMEWORK_DESIGN.md §3.2).

SENTIMENT_DIRECTION_DATASET: tuple[SentimentDirectionExample, ...] = (
    {
        "name": "large_order_win",
        "articles": (
            {
                "title": "Company wins record order worth Rs 5000 crore",
                "description": (
                    "Shares rally over 5% as brokerages upgrade the stock "
                    "citing robust growth and strong deal pipeline"
                ),
            },
        ),
        "expected_direction": "positive",
        "rationale": (
            "A large order win, analyst upgrade, and rally -- an "
            "unambiguous positive event with no governance angle."
        ),
    },
    {
        "name": "earnings_beat",
        "articles": (
            {
                "title": "Q2 profit surges as company beats estimates",
                "description": (
                    "Record quarterly profit driven by margin expansion "
                    "and resilient demand; management raised full-year "
                    "guidance"
                ),
            },
        ),
        "expected_direction": "positive",
        "rationale": "A clean earnings-beat-and-raise story.",
    },
    {
        "name": "buyback_and_expansion",
        "articles": (
            {
                "title": (
                    "Board approves buyback and special dividend after " "strong Q3"
                ),
                "description": (
                    "Company announces expansion into new markets, "
                    "milestone partnership with global tech major"
                ),
            },
        ),
        "expected_direction": "positive",
        "rationale": (
            "Capital-return (buyback/dividend) plus a growth story -- "
            "positive on two independent axes."
        ),
    },
    {
        "name": "acquisition_and_order_inflow",
        "articles": (
            {
                "title": (
                    "Company completes acquisition, sees inflow of new " "orders"
                ),
                "description": (
                    "Analysts bullish on outlook citing accelerating "
                    "growth and strong order book"
                ),
            },
        ),
        "expected_direction": "positive",
        "rationale": "M&A plus order-book strength, no negative signal.",
    },
    {
        "name": "guidance_cut",
        "articles": (
            {
                "title": ("Company misses Q2 estimates, cuts full-year guidance"),
                "description": (
                    "Stock falls sharply as management flags weak demand "
                    "and margin decline; analysts downgrade rating"
                ),
            },
        ),
        "expected_direction": "negative",
        "rationale": (
            "A guidance cut with an analyst downgrade -- the canonical "
            "negative earnings event, no governance angle."
        ),
    },
    {
        "name": "weak_demand_rising_debt",
        "articles": (
            {
                "title": "Company reports weak Q3 as demand slumps",
                "description": (
                    "Analysts flag rising debt and margin decline; "
                    "brokerage issues downgrade citing execution risk"
                ),
            },
        ),
        "expected_direction": "negative",
        "rationale": (
            "Cyclical weakness (demand slump, leverage, downgrade) with "
            "no scandal-adjacent language -- must NOT trip a red flag."
        ),
    },
    {
        "name": "layoffs_and_underperformance",
        "articles": (
            {
                "title": "Company announces layoffs after weak earnings",
                "description": (
                    "Stock underperforms sector as concerns grow over "
                    "margin decline and loss of market share"
                ),
            },
        ),
        "expected_direction": "negative",
        "rationale": "Operational weakness -- layoffs, underperformance.",
    },
    {
        "name": "lawsuit_and_penalty",
        "articles": (
            {
                "title": ("Company faces lawsuit, slapped with regulatory " "penalty"),
                "description": (
                    "Fine imposed after compliance lapse; stock falls on "
                    "concerns over legal costs and risk"
                ),
            },
        ),
        "expected_direction": "negative",
        "rationale": (
            "A lawsuit/penalty/fine -- negative, but deliberately phrased "
            "without any RED_FLAG_PHRASES substring (no 'sebi', "
            "'fraud', 'investigation', 'probe', 'regulatory action', "
            "etc.) so it stays a directional-only negative case, not one "
            "of the 3 dedicated scandal cases below."
        ),
    },
    {
        "name": "mixed_profit_vs_revenue_miss",
        "articles": (
            {
                "title": (
                    "Company reports mixed Q2: profit rises but revenue "
                    "misses expectations"
                ),
                "description": (
                    "Stock little changed as strong margins offset weak "
                    "topline; brokerages maintain hold rating"
                ),
            },
        ),
        "expected_direction": "neutral",
        "rationale": (
            "Deliberately balanced: 'profit'/'strong' (positive) exactly "
            "offset 'misses'/'weak' (negative) under the keyword scorer, "
            "netting to a genuine neutral -- tests that the agent doesn't "
            "force a direction on truly mixed news."
        ),
    },
    {
        "name": "routine_agm_notice",
        "articles": (
            {
                "title": (
                    "Company schedules annual general meeting for " "shareholders"
                ),
                "description": (
                    "Board to discuss routine agenda items including "
                    "auditor appointment and administrative matters"
                ),
            },
        ),
        "expected_direction": "neutral",
        "rationale": (
            "A genuinely no-signal corporate housekeeping announcement -- "
            "no keyword hits either direction, no red flags."
        ),
    },
)


# ---------------------------------------------------------------------------
# 3 known-scandal test cases -- held out for the red-flag detection check
# ---------------------------------------------------------------------------
#
# Each is built to trip multiple RED_FLAG_PHRASES substrings so the
# eval isn't relying on a single fragile keyword match.

SENTIMENT_SCANDAL_DATASET: tuple[SentimentScandalExample, ...] = (
    {
        "name": "sebi_regulatory_investigation",
        "articles": (
            {
                "title": (
                    "SEBI launches investigation into company for alleged "
                    "accounting irregularities"
                ),
                "description": (
                    "Regulator issues show-cause notice; probe covers "
                    "related-party transactions from last three years"
                ),
            },
        ),
        "expected_flag_keywords": ("sebi", "investigation", "probe"),
        "rationale": (
            "A textbook SEBI regulatory-action story -- the design doc's "
            "'well-documented regulatory action' scandal category."
        ),
    },
    {
        "name": "accounting_fraud_restatement",
        "articles": (
            {
                "title": (
                    "Company restates financials after auditor flags "
                    "accounting fraud"
                ),
                "description": (
                    "Whistleblower complaint triggers internal probe; "
                    "board initiates forensic audit amid restatement "
                    "concerns"
                ),
            },
        ),
        "expected_flag_keywords": ("fraud", "whistleblower", "restatement"),
        "rationale": (
            "The design doc's 'accounting-restatement episode' scandal "
            "category, with a whistleblower angle for good measure."
        ),
    },
    {
        "name": "insider_trading_governance_scandal",
        "articles": (
            {
                "title": (
                    "Promoter group charged with insider trading by " "regulator"
                ),
                "description": (
                    "Investigation finds pledged shares breached "
                    "disclosure norms; corporate governance concerns "
                    "mount as MD resigns"
                ),
            },
        ),
        "expected_flag_keywords": (
            "charged",
            "insider trading",
            "investigation",
            "corporate governance",
            "md resign",
        ),
        "rationale": (
            "The design doc's 'governance controversy' scandal category "
            "-- insider trading plus a leadership departure under a "
            "cloud."
        ),
    },
)

__all__ = [
    "ArticleInput",
    "SentimentDirection",
    "SentimentDirectionExample",
    "SentimentScandalExample",
    "SENTIMENT_DIRECTION_DATASET",
    "SENTIMENT_SCANDAL_DATASET",
]
