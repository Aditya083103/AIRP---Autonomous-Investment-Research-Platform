# backend/services/memo_generator.py
"""
AIRP -- Investment Memo Generator (T-042)

Takes the InvestmentDecision produced by the Portfolio Manager (T-041)
plus the full InvestmentState and renders a structured, ~2-page
Investment Memo in Markdown: Executive Summary, Investment Thesis, Bull
Case, Bear Case, Risk Analysis, Valuation, and Recommendation.

This module performs no LLM calls of its own. Every prose section in
the memo (executive_summary, investment_thesis, bull_case, bear_case,
risk_summary, valuation_summary, contrarian_response) was already
written by the Portfolio Manager's Stage 2 narrative synthesis in T-041.
T-042's job is structural: assemble those sections plus the structured
numeric data (verdict, conviction, price target, key risks, key
catalysts, agent weights) into one coherently formatted, readable
document -- and do it deterministically so the memo never fails to
render even if downstream PDF export (T-043) is unavailable.

Acceptance criteria (T-042):
  * Memo generated for TCS
  * All sections populated
  * Readable by a non-technical person

Design decisions
-----------------
Why Markdown and not HTML/PDF directly?
T-043 (separate task) owns PDF export via WeasyPrint. Markdown is the
natural intermediate format: it is human-readable on its own (satisfies
"readable by non-technical person" without any rendering step at all),
trivially convertible to HTML for WeasyPrint, and is what
InvestmentState.memo_markdown was already typed to hold (see
backend/graph/state.py). Keeping T-042 format-agnostic at the data layer
and Markdown at the presentation layer means T-043 can convert
Markdown -> HTML -> PDF without this module needing any awareness of
PDF libraries at all.

Why no LLM call here?
The Portfolio Manager's Stage 2 synthesis already produced every prose
sentence this memo needs. Re-summarising via a second LLM call would
risk introducing details that were not in the original committee
debate (the exact failure mode key_risks/key_catalysts/debate-grounding
were designed in T-041 to avoid) and would double the LLM cost and
latency per analysis for no benefit. T-042 is purely a formatting and
assembly layer.

Why does the memo render even when the decision has an error?
A degraded analysis (missing ticker, all agents failed) still produces
a valid -- if minimal -- InvestmentDecision per T-041's "agents never
raise" contract. The memo generator honours that same contract: it
never raises, and always returns a complete, readable document, even
if that document's content is "analysis could not be completed" rather
than a full investment case. A blank/missing memo would be a worse user
experience than a clearly-labelled incomplete one.

Public interface
-----------------
  generate_investment_memo(state)            -> dict   LangGraph node
  _build_memo_markdown(...)                  -> str    pure assembly
  _build_header_section(...)                 -> str
  _build_executive_summary_section(...)      -> str
  _build_thesis_section(...)                 -> str
  _build_bull_case_section(...)              -> str
  _build_bear_case_section(...)              -> str
  _build_risk_section(...)                   -> str
  _build_valuation_section(...)              -> str
  _build_recommendation_section(...)         -> str
  _format_agent_weights_table(...)           -> str
  _non_empty(...)                            -> str    fallback helper
"""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

_FALLBACK_TEXT = (
    "Not available -- this section could not be completed for the " "current analysis."
)

_VERDICT_LABELS: dict[str, str] = {
    "BUY": "BUY",
    "HOLD": "HOLD",
    "SELL": "SELL",
}

_VERDICT_PLAIN_ENGLISH: dict[str, str] = {
    "BUY": (
        "The committee recommends buying this stock. The weight of "
        "evidence across fundamentals, technicals, sentiment, macro "
        "conditions, risk, and valuation supports taking a position."
    ),
    "HOLD": (
        "The committee recommends holding off on a new position for "
        "now. The evidence is mixed or inconclusive, and a clearer "
        "signal is needed before committing capital."
    ),
    "SELL": (
        "The committee recommends against buying this stock, or "
        "exiting an existing position. Risk factors or valuation "
        "concerns outweigh the case for investment at this time."
    ),
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _non_empty(text: Optional[str], fallback: str = _FALLBACK_TEXT) -> str:
    """Return text if it is a non-empty string, else a readable fallback."""
    if text and text.strip():
        return text.strip()
    return fallback


def _format_conviction_label(conviction_score: int) -> str:
    """Translate a 1-10 conviction score into a plain-English label."""
    if conviction_score >= 8:
        return f"{conviction_score}/10 (high conviction)"
    if conviction_score >= 5:
        return f"{conviction_score}/10 (moderate conviction)"
    return f"{conviction_score}/10 (low conviction -- treat with caution)"


def _format_agent_weights_table(agent_weights: dict[str, float]) -> str:
    """Render the agent_weights dict as a small Markdown table."""
    if not agent_weights or not any(agent_weights.values()):
        return (
            "_Agent weighting was not available for this analysis "
            "(one or more agents may have failed to run)._"
        )

    display_names = {
        "fundamental_analyst": "Fundamental Analyst",
        "technical_analyst": "Technical Analyst",
        "news_sentiment": "News Sentiment Agent",
        "macro_economist": "Macro Economist",
        "risk_officer": "Risk Officer",
        "contrarian_investor": "Contrarian Investor",
        "valuation_agent": "Valuation Agent",
    }

    rows = ["| Committee Member | Weight |", "|---|---|"]
    for key, label in display_names.items():
        weight = agent_weights.get(key, 0.0)
        rows.append(f"| {label} | {weight * 100:.0f}% |")
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _build_header_section(
    company_name: str,
    ticker: str,
    verdict: str,
    conviction_score: int,
    price_target: Optional[str],
    time_horizon: str,
    generated_at: str,
) -> str:
    verdict_label = _VERDICT_LABELS.get(verdict, verdict)
    lines = [
        f"# Investment Memo: {company_name} ({ticker})",
        "",
        "**AIRP -- Autonomous Investment Research Platform**",
        f"*Generated: {generated_at}*",
        "",
        "| | |",
        "|---|---|",
        f"| **Recommendation** | **{verdict_label}** |",
        f"| **Conviction** | {_format_conviction_label(conviction_score)} |",
        f"| **Price Target** | {price_target or 'Not available'} |",
        f"| **Time Horizon** | {time_horizon} |",
        "",
        "---",
    ]
    return "\n".join(lines)


def _build_executive_summary_section(executive_summary: str) -> str:
    return "\n".join(
        [
            "## 1. Executive Summary",
            "",
            _non_empty(
                executive_summary,
                "An executive summary could not be generated for this "
                "analysis. Please review the individual sections below "
                "for available detail.",
            ),
        ]
    )


def _build_thesis_section(
    verdict: str,
    investment_thesis: str,
) -> str:
    plain_english = _VERDICT_PLAIN_ENGLISH.get(verdict, "")
    parts = ["## 2. Investment Thesis", ""]
    if plain_english:
        parts.append(plain_english)
        parts.append("")
    parts.append(_non_empty(investment_thesis))
    return "\n".join(parts)


def _build_bull_case_section(bull_case: str, key_catalysts: list[str]) -> str:
    parts = ["## 3. Bull Case", "", _non_empty(bull_case), ""]
    if key_catalysts:
        parts.append("**Potential catalysts:**")
        parts.append("")
        for catalyst in key_catalysts:
            parts.append(f"- {catalyst}")
    return "\n".join(parts)


def _build_bear_case_section(
    bear_case: str,
    contrarian_response: str,
) -> str:
    parts = [
        "## 4. Bear Case",
        "",
        _non_empty(bear_case),
        "",
        "**How the committee addressed this:**",
        "",
        _non_empty(
            contrarian_response,
            "The dissenting view was considered alongside the rest of "
            "the committee's evidence in reaching the final verdict.",
        ),
    ]
    return "\n".join(parts)


def _build_risk_section(risk_summary: str, key_risks: list[str]) -> str:
    parts = ["## 5. Risk Analysis", "", _non_empty(risk_summary), ""]
    if key_risks:
        parts.append("**Key risks to monitor:**")
        parts.append("")
        for i, risk_item in enumerate(key_risks, start=1):
            parts.append(f"{i}. {risk_item}")
    return "\n".join(parts)


def _build_valuation_section(
    valuation_summary: str, price_target: Optional[str]
) -> str:
    parts = ["## 6. Valuation", "", _non_empty(valuation_summary)]
    if price_target:
        parts.append("")
        parts.append(f"**Implied price target:** {price_target}")
    return "\n".join(parts)


def _build_recommendation_section(
    verdict: str,
    conviction_score: int,
    time_horizon: str,
    summary: str,
    agent_weights: dict[str, float],
    debate_rounds_used: int,
) -> str:
    verdict_label = _VERDICT_LABELS.get(verdict, verdict)
    conviction_label = _format_conviction_label(conviction_score)
    parts = [
        "## 7. Recommendation",
        "",
        f"**Final verdict: {verdict_label}** -- conviction {conviction_label}",
        "",
        _non_empty(
            summary,
            f"{verdict_label} -- see sections above for the full "
            f"committee analysis.",
        ),
        "",
        f"Suggested holding period: **{time_horizon}**. This decision "
        f"was reached after {debate_rounds_used} round"
        f"{'s' if debate_rounds_used != 1 else ''} of committee debate.",
        "",
        "**How the committee weighed the evidence:**",
        "",
        _format_agent_weights_table(agent_weights),
    ]
    return "\n".join(parts)


def _build_disclaimer_section() -> str:
    return "\n".join(
        [
            "---",
            "",
            "*This memo was generated autonomously by AIRP, an AI "
            "investment research system, for educational and portfolio "
            "demonstration purposes only. It is not financial advice and "
            "should not be the sole basis for any investment decision. "
            "Always conduct independent research or consult a licensed "
            "financial advisor before investing.*",
        ]
    )


# ---------------------------------------------------------------------------
# Top-level assembly
# ---------------------------------------------------------------------------


def _build_memo_markdown(
    company_name: str,
    ticker: str,
    decision: dict[str, Any],
    generated_at: str,
) -> str:
    """
    Assemble the full Markdown memo from an InvestmentDecision dict
    (decision.model_dump()) and the company/ticker identifiers. Never
    raises -- every field access goes through a fallback so a partially
    populated or error-flagged decision still produces a complete,
    readable document.
    """
    verdict = str(decision.get("verdict") or "HOLD")
    conviction_score = int(decision.get("conviction_score") or 1)
    price_target = decision.get("price_target")
    time_horizon = str(decision.get("time_horizon") or "12 months")
    debate_rounds_used = int(decision.get("debate_rounds_used") or 1)
    agent_weights = decision.get("agent_weights") or {}
    key_risks = decision.get("key_risks") or []
    key_catalysts = decision.get("key_catalysts") or []

    sections = [
        _build_header_section(
            company_name=company_name,
            ticker=ticker,
            verdict=verdict,
            conviction_score=conviction_score,
            price_target=price_target,
            time_horizon=time_horizon,
            generated_at=generated_at,
        ),
        _build_executive_summary_section(decision.get("executive_summary", "")),
        _build_thesis_section(verdict, decision.get("investment_thesis", "")),
        _build_bull_case_section(decision.get("bull_case", ""), key_catalysts),
        _build_bear_case_section(
            decision.get("bear_case", ""), decision.get("contrarian_response", "")
        ),
        _build_risk_section(decision.get("risk_summary", ""), key_risks),
        _build_valuation_section(decision.get("valuation_summary", ""), price_target),
        _build_recommendation_section(
            verdict=verdict,
            conviction_score=conviction_score,
            time_horizon=time_horizon,
            summary=decision.get("summary", ""),
            agent_weights=agent_weights,
            debate_rounds_used=debate_rounds_used,
        ),
        _build_disclaimer_section(),
    ]

    return "\n\n".join(sections) + "\n"


def _build_no_decision_memo(company_name: str, ticker: str, generated_at: str) -> str:
    """
    Fallback memo used when state["decision"] is entirely absent (e.g.
    the pipeline failed before the Portfolio Manager ran). Still a
    complete, readable Markdown document -- never an empty string.
    """
    return (
        "\n\n".join(
            [
                f"# Investment Memo: {company_name} ({ticker})",
                f"*Generated: {generated_at}*",
                "\n".join(
                    [
                        "## Analysis Incomplete",
                        "",
                        "This analysis could not be completed. The investment "
                        "committee's decision is not available, most likely "
                        "because an earlier step in the pipeline did not "
                        "finish successfully. Please re-run the analysis or "
                        "contact support if the issue persists.",
                    ]
                ),
                _build_disclaimer_section(),
            ]
        )
        + "\n"
    )


# ---------------------------------------------------------------------------
# LangGraph node entry point
# ---------------------------------------------------------------------------


def generate_investment_memo(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph node entry point (T-042). Reads state["decision"] (the
    InvestmentDecision produced by the Portfolio Manager in T-041) and
    state["company_name"] / state["ticker"], and returns the partial
    state update containing the rendered Markdown memo.

    Never raises -- on any failure, falls back to a minimal but complete
    "analysis incomplete" memo rather than leaving memo_markdown unset.
    """
    company_name = state.get("company_name", "Unknown Company")
    ticker = state.get("ticker", "UNKNOWN")
    generated_at = datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")

    decision = state.get("decision")

    try:
        if decision:
            memo_markdown = _build_memo_markdown(
                company_name=company_name,
                ticker=ticker,
                decision=decision,
                generated_at=generated_at,
            )
        else:
            logger.warning(
                "generate_investment_memo: no decision in state for "
                "job_id=%s; rendering fallback memo",
                state.get("job_id", "unknown"),
            )
            memo_markdown = _build_no_decision_memo(
                company_name=company_name, ticker=ticker, generated_at=generated_at
            )
    except Exception as exc:  # noqa: BLE001 -- this node must never raise
        logger.warning(
            "generate_investment_memo: memo assembly failed (%s); "
            "rendering fallback memo",
            exc,
        )
        memo_markdown = _build_no_decision_memo(
            company_name=company_name, ticker=ticker, generated_at=generated_at
        )

    return {"memo_markdown": memo_markdown}


__all__ = [
    "generate_investment_memo",
    "_build_memo_markdown",
    "_build_no_decision_memo",
    "_build_header_section",
    "_build_executive_summary_section",
    "_build_thesis_section",
    "_build_bull_case_section",
    "_build_bear_case_section",
    "_build_risk_section",
    "_build_valuation_section",
    "_build_recommendation_section",
    "_format_agent_weights_table",
    "_format_conviction_label",
    "_non_empty",
]
