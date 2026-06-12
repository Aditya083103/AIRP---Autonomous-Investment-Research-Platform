# backend/agents/fundamental_analyst.py
"""
AIRP — Fundamental Analyst Agent (T-022)

Persona: seasoned buy-side fundamental analyst with 20 years of experience
covering Indian equities (NSE/BSE).  Specialises in quality-of-earnings
analysis, balance-sheet stress-testing, and free cash flow decomposition.

Mandate
───────
Analyse a company's financial health over the last 4 fiscal years using
two data tools:
  * fetch_financials  — income statement, balance sheet, cash flow (4 years)
  * fetch_ratios      — PE, PB, ROE, ROCE, D/E, EV/EBITDA

Produce a validated ``FundamentalAnalysis`` Pydantic model with:
  * score 1–10 (composite fundamental quality)
  * revenue_trend / profit_trend / debt_level / fcf_status (qualitative labels)
  * strengths[], risks[] (concrete observations, not generic statements)
  * summary (2–3 sentences, portfolio-manager-ready)

Public interface
────────────────
  run_fundamental_analysis(state)  →  dict  (LangGraph node function)
  _score_financials(...)           →  int   (pure, unit-testable scoring logic)
  _assess_trends(...)              →  dict  (pure, unit-testable label logic)
  _build_agent_prompt(...)         →  str   (prompt builder, unit-testable)

Design decisions
────────────────
* NO ``from __future__ import annotations`` — breaks Pydantic v2 union
  resolution (established AIRP rule from T-010).
* The LLM is used ONLY to write strengths[], risks[], and summary — the
  numerical score and qualitative labels are computed deterministically from
  the tool outputs so they are reproducible without an LLM call.
* Tool calls happen BEFORE the LLM call.  The LLM receives pre-processed
  structured data, never raw DataFrames or JSON blobs.
* Error convention: always returns a dict; never raises.  On any failure
  the returned FundamentalAnalysis has ``error`` set and ``score=1``.
* LangSmith tracing is automatic when LANGCHAIN_TRACING_V2=true and
  LANGSMITH_API_KEY is set — no additional code needed; every LLM call and
  tool call in this module is captured.

Usage (inside LangGraph node, Phase 3)
───────────────────────────────────────
    from agents.fundamental_analyst import run_fundamental_analysis

    # state is an InvestmentState TypedDict
    updated_state = run_fundamental_analysis(state)
    # updated_state["fundamental"] is a dict representation of FundamentalAnalysis
"""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.llm_factory import get_llm
from backend.agents.output_models import FundamentalAnalysis
from backend.agents.tracing import traced_agent
from backend.tools.financials import fetch_financials
from backend.tools.ratios import fetch_ratios

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent persona — system prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a seasoned buy-side fundamental analyst with 20 years \
of experience covering Indian equities on NSE and BSE. You specialise in \
quality-of-earnings analysis, balance-sheet stress-testing, and free cash flow \
decomposition.

Your job is to evaluate a company's financial health based on structured data \
from the last 4 fiscal years and produce a concise, investment-committee-ready \
assessment.

RULES:
1. Be specific — cite actual numbers, not vague generalities.
2. Strengths and risks must be concrete observations tied to data points.
3. The summary must be 2–3 sentences maximum, written for a Portfolio Manager.
4. Do NOT use markdown, bullet symbols, or headers in your output.
5. Respond ONLY with valid JSON matching the exact schema described below.
6. Do not invent numbers. If data is missing, acknowledge it explicitly.

OUTPUT SCHEMA (strict JSON, no markdown fences):
{
  "strengths": ["<1-sentence strength with data point>", ...],
  "risks": ["<1-sentence risk with data point>", ...],
  "summary": "<2-3 sentence investment-committee summary>"
}

Produce 3-5 strengths and 3-5 risks. Every item must reference a specific \
financial metric or ratio."""

# ---------------------------------------------------------------------------
# Pure helper: deterministic scoring
# ---------------------------------------------------------------------------

# Score bands for individual dimensions (revenue CAGR, margins, D/E, FCF yield)
# Each dimension contributes equally to the composite score.
_REVENUE_CAGR_THRESHOLDS = [
    (15.0, 3),  # > 15% CAGR → 3 points
    (8.0, 2),  # > 8%        → 2 points
    (3.0, 1),  # > 3%        → 1 point
    (0.0, 0),  # positive    → 0 points
]

_NET_MARGIN_THRESHOLDS = [
    (20.0, 2),  # > 20% net margin → 2 points
    (12.0, 1),  # > 12%            → 1 point
]

_ROE_THRESHOLDS = [
    (20.0, 2),  # > 20% ROE → 2 points
    (12.0, 1),  # > 12%     → 1 point
]

_DE_THRESHOLDS = [
    (0.0, 2),  # net cash (D/E ≤ 0)   → 2 points
    (0.5, 1),  # conservative (≤ 0.5) → 1 point
]

_FCF_YIELD_THRESHOLDS = [
    (5.0, 1),  # FCF margin ≥ 5% of revenue → 1 point
]


def _band_score(
    value: float | None,
    thresholds: list[tuple[float, int]],
) -> int:
    """
    Return the score for a metric by comparing it against ordered thresholds.

    Thresholds are evaluated from highest to lowest.  The first threshold
    the value meets or exceeds determines the score.  Returns 0 when the
    value is None or below all thresholds.
    """
    if value is None:
        return 0
    for threshold, points in thresholds:
        if value >= threshold:
            return points
    return 0


def _revenue_cagr(
    income_records: list[dict[str, Any]],
) -> float | None:
    """
    Compute revenue CAGR over the available fiscal years.

    yFinance returns years most-recent-first so index 0 = latest, index -1 =
    oldest.  Returns None if fewer than 2 years have revenue data.
    """
    revenues: list[float] = [
        float(r["revenue_crores"])
        for r in income_records
        if r.get("revenue_crores") is not None
    ]
    if len(revenues) < 2:
        return None
    latest: float = revenues[0]
    oldest: float = revenues[-1]
    if oldest <= 0:
        return None
    n_years: int = len(revenues) - 1
    cagr: float = ((latest / oldest) ** (1.0 / n_years) - 1.0) * 100
    return round(cagr, 2)


def _score_financials(
    financials: dict[str, Any],
    ratios: dict[str, Any],
) -> int:
    """
    Compute a composite fundamental quality score from 1 (poor) to 10 (excellent).

    The score is fully deterministic — no LLM involved.  It is derived from
    six dimensions weighted by their max contribution:

      Revenue CAGR     (0–3 pts)  — growth engine quality
      Net margin       (0–2 pts)  — profitability
      ROE              (0–2 pts)  — capital efficiency
      Debt/Equity      (0–2 pts)  — balance sheet safety
      FCF margin       (0–1 pt)   — cash conversion
      ─────────────────────────
      Raw total        (0–10 pts) → clipped to [1, 10]

    Returns 1 (minimum) when data is severely missing to signal unreliable
    assessment rather than a falsely neutral mid-range score.
    """
    income = financials.get("income_statement", [])
    cashflow = financials.get("cash_flow", [])

    # Revenue CAGR
    cagr = _revenue_cagr(income)
    revenue_pts = _band_score(cagr, _REVENUE_CAGR_THRESHOLDS)

    # Most-recent-year net margin
    net_margin = income[0].get("net_margin_pct") if income else None
    margin_pts = _band_score(net_margin, _NET_MARGIN_THRESHOLDS)

    # ROE from ratios (preferred) or derive from financials
    roe = ratios.get("roe_pct")
    roe_pts = _band_score(roe, _ROE_THRESHOLDS)

    # Debt/Equity from ratios
    de = ratios.get("debt_to_equity")
    if de is None:
        bs = financials.get("balance_sheet", [])
        de = bs[0].get("debt_to_equity") if bs else None
    # D/E scoring: lower is better
    de_pts = 0
    if de is not None:
        if de <= 0:
            de_pts = 2
        elif de <= 0.5:
            de_pts = 1

    # FCF margin (most recent year)
    fcf_margin = cashflow[0].get("fcf_margin_pct") if cashflow else None
    fcf_pts = _band_score(fcf_margin, _FCF_YIELD_THRESHOLDS)

    raw = revenue_pts + margin_pts + roe_pts + de_pts + fcf_pts

    # If we have almost no data, return minimum to signal unreliability
    data_available = sum(
        1 for x in [cagr, net_margin, roe, de, fcf_margin] if x is not None
    )
    if data_available < 2:
        return 1

    return max(1, min(10, raw))


def _assess_trends(
    financials: dict[str, Any],
    ratios: dict[str, Any],
) -> dict[str, str]:
    """
    Derive four qualitative labels from the financial data.

    Returns a dict with keys:
      revenue_trend  — 'growing' | 'stable' | 'declining' | 'insufficient_data'
      profit_trend   — 'improving' | 'stable' | 'declining' | 'insufficient_data'
      debt_level     — 'low' | 'moderate' | 'high' | 'net_cash' | 'unknown'
      fcf_status     — 'strong' | 'adequate' | 'weak' | 'negative' | 'unknown'

    These labels are passed to the LLM as structured context, not freeform.
    """
    income = financials.get("income_statement", [])
    cashflow = financials.get("cash_flow", [])
    balance = financials.get("balance_sheet", [])

    # Revenue trend: compare latest vs 2-year-ago (index 0 vs index 2)
    revenue_trend = "insufficient_data"
    if len(income) >= 2:
        r0 = income[0].get("revenue_crores")
        r_old = income[-1].get("revenue_crores")
        if r0 is not None and r_old is not None and r_old > 0:
            pct = ((r0 - r_old) / r_old) * 100
            if pct >= 5:
                revenue_trend = "growing"
            elif pct <= -5:
                revenue_trend = "declining"
            else:
                revenue_trend = "stable"

    # Profit trend: net margin direction
    profit_trend = "insufficient_data"
    margins = [
        r.get("net_margin_pct") for r in income if r.get("net_margin_pct") is not None
    ]
    if len(margins) >= 2:
        delta = margins[0] - margins[-1]
        if delta >= 1.5:
            profit_trend = "improving"
        elif delta <= -1.5:
            profit_trend = "declining"
        else:
            profit_trend = "stable"

    # Debt level: use D/E from ratios or balance sheet
    de = ratios.get("debt_to_equity")
    if de is None and balance:
        de = balance[0].get("debt_to_equity")
    debt_level = "unknown"
    if de is not None:
        if de < 0:
            debt_level = "net_cash"
        elif de <= 0.3:
            debt_level = "low"
        elif de <= 1.0:
            debt_level = "moderate"
        else:
            debt_level = "high"

    # FCF status: based on FCF margin of most recent year
    fcf_status = "unknown"
    if cashflow:
        fcf_margin = cashflow[0].get("fcf_margin_pct")
        fcf_crores = cashflow[0].get("free_cash_flow_crores")
        if fcf_crores is not None and fcf_crores < 0:
            fcf_status = "negative"
        elif fcf_margin is not None:
            if fcf_margin >= 15:
                fcf_status = "strong"
            elif fcf_margin >= 5:
                fcf_status = "adequate"
            else:
                fcf_status = "weak"

    return {
        "revenue_trend": revenue_trend,
        "profit_trend": profit_trend,
        "debt_level": debt_level,
        "fcf_status": fcf_status,
    }


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _build_agent_prompt(
    company_name: str,
    ticker: str,
    financials: dict[str, Any],
    ratios: dict[str, Any],
    score: int,
    trends: dict[str, str],
) -> str:
    """
    Build the user-turn prompt sent to the LLM.

    The LLM receives pre-processed, human-readable data — not raw JSON blobs.
    This keeps the context window compact and the output reliable.
    """
    income = financials.get("income_statement", [])
    cashflow = financials.get("cash_flow", [])
    balance = financials.get("balance_sheet", [])

    def _fmt(val: Any, suffix: str = "") -> str:
        if val is None:
            return "N/A"
        if isinstance(val, float):
            return f"{val:,.1f}{suffix}"
        return f"{val}{suffix}"

    # Build year-by-year income summary (most recent first)
    income_lines = []
    for yr in income[:4]:
        income_lines.append(
            f"  {yr.get('fiscal_year', '?')}: "
            f"Revenue ₹{_fmt(yr.get('revenue_crores'))} Cr | "
            f"Net Income ₹{_fmt(yr.get('net_income_crores'))} Cr | "
            f"Net Margin {_fmt(yr.get('net_margin_pct'), '%')} | "
            f"Op Margin {_fmt(yr.get('operating_margin_pct'), '%')}"
        )

    # Balance sheet most recent
    bs = balance[0] if balance else {}
    bs_summary = (
        f"Total Debt ₹{_fmt(bs.get('total_debt_crores'))} Cr | "
        f"Cash ₹{_fmt(bs.get('cash_crores'))} Cr | "
        f"D/E {_fmt(bs.get('debt_to_equity'))} | "
        f"Current Ratio {_fmt(bs.get('current_ratio'))}"
    )

    # FCF most recent
    cf = cashflow[0] if cashflow else {}
    cf_summary = (
        f"FCF ₹{_fmt(cf.get('free_cash_flow_crores'))} Cr | "
        f"FCF Margin {_fmt(cf.get('fcf_margin_pct'), '%')} | "
        f"Op CF ₹{_fmt(cf.get('operating_cash_flow_crores'))} Cr"
    )

    # Ratios
    ratios_summary = (
        f"PE {_fmt(ratios.get('pe_ratio'))}x | "
        f"PB {_fmt(ratios.get('pb_ratio'))}x | "
        f"ROE {_fmt(ratios.get('roe_pct'), '%')} | "
        f"ROCE {_fmt(ratios.get('roce_pct'), '%')} | "
        f"EV/EBITDA {_fmt(ratios.get('ev_to_ebitda'))}x"
    )

    income_block = "\n".join(income_lines) or "  Data unavailable"

    return f"""Analyse the following financial data for {company_name} ({ticker}).

FUNDAMENTAL QUALITY SCORE (pre-computed): {score}/10
TREND LABELS (pre-computed):
  Revenue trend : {trends['revenue_trend']}
  Profit trend  : {trends['profit_trend']}
  Debt level    : {trends['debt_level']}
  FCF status    : {trends['fcf_status']}

INCOME STATEMENT (4-year, INR Crores, most recent first):
{income_block}

BALANCE SHEET (most recent year):
  {bs_summary}

CASH FLOW (most recent year):
  {cf_summary}

VALUATION RATIOS:
  {ratios_summary}

Data warnings from sources: \
{', '.join(financials.get('data_warnings', [])) or 'None'}

Using this data, produce the JSON output as specified in the system prompt.
Cite specific numbers from the data above in every strength and risk item."""


# ---------------------------------------------------------------------------
# Core agent logic (separated from LangGraph node for testability)
# ---------------------------------------------------------------------------


def _run_fundamental_analysis_core(
    analysis_id: str,
    company_name: str,
    ticker: str,
) -> FundamentalAnalysis:
    """
    Core agent logic — fetch data, score, call LLM, return FundamentalAnalysis.

    Separated from ``run_fundamental_analysis`` so it can be called directly
    in tests with controlled inputs (no LangGraph state required).

    Raises:
        Never — on any failure returns FundamentalAnalysis with error set.
    """
    # ── Step 1: Fetch financial statements ──────────────────────────────
    logger.info(
        "Fundamental analyst: fetching financials ticker=%s analysis=%s",
        ticker,
        analysis_id,
    )
    try:
        financials = fetch_financials.invoke({"ticker": ticker})
    except Exception as exc:
        logger.exception("fetch_financials failed for %s", ticker)
        financials = {
            "error": "fetch_failed",
            "message": str(exc),
            "income_statement": [],
            "balance_sheet": [],
            "cash_flow": [],
            "data_warnings": [f"fetch_financials failed: {exc}"],
        }

    if "error" in financials:
        logger.warning(
            "fetch_financials returned error for %s: %s",
            ticker,
            financials.get("message"),
        )
        financials = {
            "income_statement": [],
            "balance_sheet": [],
            "cash_flow": [],
            "data_warnings": [financials.get("message", "financials unavailable")],
        }

    # ── Step 2: Fetch valuation ratios ───────────────────────────────────
    logger.info("Fundamental analyst: fetching ratios ticker=%s", ticker)
    try:
        ratios = fetch_ratios.invoke({"ticker": ticker})
    except Exception as exc:
        logger.exception("fetch_ratios failed for %s", ticker)
        ratios = {
            "error": "fetch_failed",
            "message": str(exc),
        }

    if "error" in ratios:
        logger.warning(
            "fetch_ratios returned error for %s: %s",
            ticker,
            ratios.get("message"),
        )
        ratios = {}

    # ── Step 3: Deterministic scoring and trend labels ───────────────────
    score = _score_financials(financials, ratios)
    trends = _assess_trends(financials, ratios)

    # ── Step 4: Build supplementary field values from tool data ──────────
    income = financials.get("income_statement", [])
    cashflow = financials.get("cash_flow", [])
    balance = financials.get("balance_sheet", [])

    revenue_growth_pct = _revenue_cagr(income)
    net_margin = income[0].get("net_margin_pct") if income else None
    op_margin = income[0].get("operating_margin_pct") if income else None
    gross_margin = income[0].get("gross_margin_pct") if income else None
    fcf_crores = cashflow[0].get("free_cash_flow_crores") if cashflow else None
    debt_to_equity = ratios.get("debt_to_equity") or (
        balance[0].get("debt_to_equity") if balance else None
    )
    current_ratio = balance[0].get("current_ratio") if balance else None
    roe = ratios.get("roe_pct")
    roce = ratios.get("roce_pct")

    # ── Step 5: LLM call for qualitative synthesis ───────────────────────
    logger.info("Fundamental analyst: invoking LLM ticker=%s", ticker)
    strengths: list[str] = []
    risks: list[str] = []
    summary = ""

    try:
        llm = get_llm()
        prompt = _build_agent_prompt(
            company_name=company_name,
            ticker=ticker,
            financials=financials,
            ratios=ratios,
            score=score,
            trends=trends,
        )
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        response = llm.invoke(messages)
        raw_text = response.content if hasattr(response, "content") else str(response)
        # Parse JSON from LLM response
        import json
        import re

        # Strip any accidental markdown fences the LLM adds despite instructions
        cleaned = re.sub(r"```(?:json)?|```", "", raw_text).strip()
        parsed = json.loads(cleaned)

        strengths = parsed.get("strengths", [])
        risks = parsed.get("risks", [])
        summary = parsed.get("summary", "")

    except Exception as exc:
        logger.exception(
            "LLM call failed in fundamental analyst for %s: %s", ticker, exc
        )
        strengths = [f"Score {score}/10 based on deterministic financial analysis"]
        risks = [f"LLM synthesis unavailable: {exc}"]
        summary = (
            f"{company_name} receives a fundamental quality score of {score}/10. "
            f"Revenue trend: {trends['revenue_trend']}. "
            f"LLM narrative synthesis failed — review raw data."
        )

    # ── Step 6: Build and return FundamentalAnalysis ─────────────────────
    return FundamentalAnalysis(
        agent_name="fundamental_analyst",
        analysis_id=analysis_id,
        company_name=company_name,
        ticker=ticker,
        score=score,
        revenue_growth_pct=revenue_growth_pct,
        net_margin_pct=net_margin,
        operating_margin_pct=op_margin,
        gross_margin_pct=gross_margin,
        free_cash_flow_cr=fcf_crores,
        debt_to_equity=debt_to_equity,
        current_ratio=current_ratio,
        roe_pct=roe,
        roce_pct=roce,
        strengths=strengths,
        weaknesses=risks,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# LangGraph node entry point
# ---------------------------------------------------------------------------


@traced_agent("fundamental_analyst")
def run_fundamental_analysis(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph node function for the Fundamental Analyst agent.

    Reads from InvestmentState:
      - job_id       → analysis_id for the output model
      - company_name → human-readable company name
      - ticker       → Yahoo Finance ticker (e.g. 'TCS.NS')

    Writes to InvestmentState:
      - fundamental  → dict representation of FundamentalAnalysis

    Never raises — on failure, ``fundamental["error"]`` is set so the
    LangGraph router can handle the error gracefully.

    Args:
        state: InvestmentState dict (LangGraph passes the full state).

    Returns:
        Dict with key 'fundamental' containing the serialised output model.
    """
    analysis_id: str = state.get("job_id", "unknown")
    company_name: str = state.get("company_name", "Unknown Company")
    ticker: str = state.get("ticker", "")

    if not ticker:
        logger.error("run_fundamental_analysis called with empty ticker")
        result = FundamentalAnalysis(
            agent_name="fundamental_analyst",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker="UNKNOWN",
            score=1,
            error="ticker field is missing from InvestmentState",
        )
        return {"fundamental": result.model_dump()}

    try:
        result = _run_fundamental_analysis_core(
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
        )
    except Exception as exc:
        logger.exception(
            "Unhandled error in fundamental analyst node: ticker=%s", ticker
        )
        result = FundamentalAnalysis(
            agent_name="fundamental_analyst",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            score=1,
            error=f"Unhandled agent error: {exc}",
        )

    return {"fundamental": result.model_dump()}
