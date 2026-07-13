# backend/agents/portfolio_manager.py
"""
AIRP -- Portfolio Manager Agent (T-041)

Persona: Chief Investment Officer of a hedge fund. Reads the complete
InvestmentState -- all 7 prior agent outputs plus the full multi-round
debate transcript built by T-040 -- and renders the single, final,
accountable investment decision for the committee.

Mandate
-------
Produce an InvestmentDecision containing:
  * verdict               -- 'BUY' | 'HOLD' | 'SELL'
  * conviction_score       -- 1-10, must correlate with quality of
                               analysis (agreement, completeness, debate
                               length), not with how bullish/bearish the
                               signals happen to be
  * price_target           -- formatted from the Valuation Agent's DCF
  * time_horizon            -- suggested holding period for this verdict
  * bull_case / bear_case / risk_summary / valuation_summary
  * key_risks[] / key_catalysts[] -- structured lists consumed directly
    by the T-042 Investment Memo generator
  * contrarian_response     -- must name and address the Contrarian's
    strongest_argument
  * investment_thesis       -- must reference a specific point from the
    debate transcript

Acceptance criteria (T-041):
  * Portfolio Manager's decision references specific points from debate
  * Conviction score correlates with quality of analysis

Two-stage pipeline (same pattern as risk_officer.py / contrarian_investor.py
/ valuation_agent.py):
  Stage 1 -- Deterministic: agent weights, verdict, conviction, time
             horizon, price target, key_risks, key_catalysts. Fully
             unit-testable without any LLM call.
  Stage 2 -- LLM narrative synthesis: writes the prose memo sections
             around the Stage 1 numbers. The LLM is told the verdict and
             conviction explicitly and instructed not to change them --
             its only job is narrative, never the decision itself.

Public interface
-----------------
  run_portfolio_manager_decision(state)  -> dict   LangGraph node
  _run_portfolio_manager_core(...)       -> InvestmentDecision
  _compute_agent_weights(...)            -> dict[str, float]
  _determine_verdict(...)                -> str
  _score_conviction(...)                 -> int
  _determine_time_horizon(...)           -> str
  _build_price_target(...)               -> Optional[str]
  _build_key_risks(...)                  -> list[str]
  _build_key_catalysts(...)              -> list[str]
  _extract_debate_highlights(...)        -> list[str]
  _build_portfolio_manager_prompt(...)   -> str

Design decisions
-----------------
Why deterministic Stage 1?  The verdict and conviction score are the most
consequential outputs in the entire pipeline -- they must be reproducible
and unit-testable without depending on LLM determinism. See
docs/week-11/T-041-portfolio-manager.md for the full design rationale,
including why conviction tracks quality-of-analysis rather than signal
direction, and why two hard gates exist ahead of the weighted tally.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.llm_factory import get_llm
from backend.agents.output_models import InvestmentDecision
from backend.agents.tracing import traced_agent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

# Base weight assigned to each agent when all 7 are usable (sums to 1.0).
# Fundamental and Valuation carry the most weight because they are the
# only two agents grounded directly in financial-statement data; News
# Sentiment carries the least because it is the noisiest, most transient
# signal.
_BASE_AGENT_WEIGHTS: dict[str, float] = {
    "fundamental_analyst": 0.20,
    "valuation_agent": 0.20,
    "risk_officer": 0.15,
    "contrarian_investor": 0.15,
    "technical_analyst": 0.12,
    "macro_economist": 0.10,
    "news_sentiment": 0.08,
}

# Risk Officer's risk_score at or above this level is treated as
# prohibitive -- no combination of bullish signals can override it.
_PROHIBITIVE_RISK_SCORE_THRESHOLD = 8

# Contrarian's bear_conviction at or above this level is "strong" --
# matches the same threshold route_after_contrarian (T-032/T-038) uses
# to decide whether a second debate round is warranted.
_HIGH_BEAR_CONVICTION_THRESHOLD = 7

# A nominal BUY is downgraded to HOLD when both of these hold: the
# committee has at least this many critical risk flags, AND the raw
# verdict score was only marginally bullish (see _determine_verdict).
_CRITICAL_FLAGS_DOWNGRADE_THRESHOLD = 2

_MAX_KEY_RISKS = 6
_MAX_KEY_CATALYSTS = 5

_VALID_VERDICTS = ("BUY", "HOLD", "SELL")

SYSTEM_PROMPT = """You are the Chief Investment Officer (CIO) of a hedge \
fund, chairing the final session of the investment committee for AIRP \
(Autonomous Investment Research Platform).

You have already received the deterministic decision from your own \
quantitative process: the verdict, conviction score, time horizon, and \
price target are FINAL and have already been computed from the full \
weighted analysis of all seven committee members. Do NOT change them, \
contradict them, or propose a different number anywhere in your output.

YOUR JOB is narrative synthesis only: write the prose sections of the \
Investment Memo that explain, in plain English, why the committee \
reached this decision.

RULES:
1. investment_thesis MUST explicitly reference a specific point from the \
   debate transcript provided to you (name the round number or the \
   specific challenge raised).
2. contrarian_response MUST name the Contrarian's strongest_argument and \
   directly address it -- either by explaining why the committee \
   overruled it, or by acknowledging it materially limited conviction.
3. Every section must be written for a non-specialist reader: a smart \
   person with no finance background should understand exactly why this \
   verdict was reached.
4. Do not invent facts, numbers, or events that are not present in the \
   data provided to you.
5. Keep each section to 2-4 sentences except executive_summary, which \
   may run to 2-3 short paragraphs.

OUTPUT SCHEMA -- return ONLY a single JSON object with exactly these \
keys, no markdown fences, no commentary before or after:
{
  "executive_summary": "...",
  "investment_thesis": "...",
  "bull_case": "...",
  "bear_case": "...",
  "risk_summary": "...",
  "valuation_summary": "...",
  "contrarian_response": "...",
  "summary": "..."
}

The "summary" field must be a single sentence suitable for a dashboard, \
e.g. "TCS: BUY with conviction 8/10 -- strong fundamentals, reasonable \
valuation, manageable risks."

Respond with JSON only."""


# ---------------------------------------------------------------------------
# Stage 1a -- agent weights
# ---------------------------------------------------------------------------


def _compute_agent_weights(
    fundamental: dict[str, Any],
    technical: dict[str, Any],
    sentiment: dict[str, Any],
    macro: dict[str, Any],
    risk: dict[str, Any],
    contrarian: dict[str, Any],
    valuation: dict[str, Any],
) -> dict[str, float]:
    """
    Assign each of the 7 prior agents a weight in [0.0, 1.0] summing to
    1.0. Any agent that errored or produced no output gets zero weight,
    and its share is redistributed proportionally across the agents that
    did produce usable output.

    T-082: the fundamental analyst also gets zero weight when its
    ``data_quality`` is ``"insufficient"``. A missing score defaults to a
    neutral 5 inside ``_determine_verdict``'s weighted tally, so leaving
    fundamental_analyst's base weight in place would still let a
    fabricated "neutral" opinion crowd out real signal from the other six
    agents -- excluding it entirely and redistributing its weight is the
    honest outcome.
    """
    base_weights = dict(_BASE_AGENT_WEIGHTS)
    outputs: dict[str, dict[str, Any]] = {
        "fundamental_analyst": fundamental,
        "technical_analyst": technical,
        "news_sentiment": sentiment,
        "macro_economist": macro,
        "risk_officer": risk,
        "contrarian_investor": contrarian,
        "valuation_agent": valuation,
    }

    usable: dict[str, float] = {}
    for name, weight in base_weights.items():
        out = outputs.get(name) or {}
        if not out or out.get("error"):
            continue
        if name == "fundamental_analyst" and out.get("data_quality") == "insufficient":
            continue
        usable[name] = weight

    total_usable = sum(usable.values())
    if total_usable <= 0:
        # Every agent failed -- no basis for any weighting at all.
        return dict.fromkeys(base_weights, 0.0)

    # Redistribute proportionally so usable weights sum to exactly 1.0.
    normalised: dict[str, float] = {
        name: round(weight / total_usable, 4) for name, weight in usable.items()
    }
    for name in base_weights:
        if name not in normalised:
            normalised[name] = 0.0

    return normalised


# ---------------------------------------------------------------------------
# Stage 1b -- verdict
# ---------------------------------------------------------------------------


def _determine_verdict(
    fundamental: dict[str, Any],
    technical: dict[str, Any],
    sentiment: dict[str, Any],
    risk: dict[str, Any],
    contrarian: dict[str, Any],
    valuation: dict[str, Any],
    critical_flags: list[str],
) -> str:
    """
    Deterministic BUY / HOLD / SELL decision.

    Two hard gates run first -- these mirror how a real investment
    committee operates: a sufficiently bullish combination of other
    signals cannot mathematically out-vote a critical risk finding.
    After the gates, a weighted point tally across the remaining signals
    decides the verdict, with a soft downgrade rule that prevents a
    marginal BUY from surviving alongside multiple critical flags.

    T-082: Gate 2 is skipped when the fundamental analyst's
    ``data_quality`` is ``"insufficient"``. Gate 2 exists to catch a
    genuinely overvalued, genuinely weak company -- not to punish a
    company for which fundamentals data happened to be unavailable.
    ``fund_score`` already falls back to a neutral 5 when the score is
    ``None``, and 5 < 6 would otherwise fire Gate 2 on every
    insufficient-data case that is also flagged overvalued, regardless of
    whether the fundamentals are actually weak.
    """
    risk_score = int(risk.get("risk_score") or 5)
    valuation_verdict = str(valuation.get("valuation_verdict") or "fairly_valued")
    fund_data_quality = str(fundamental.get("data_quality") or "sufficient")
    fund_score = int(fundamental.get("score") or 5)
    bear_conviction = int(contrarian.get("bear_conviction") or 1)

    # -- Hard gate 1: prohibitive risk overrides everything ---------------
    if risk_score >= _PROHIBITIVE_RISK_SCORE_THRESHOLD:
        return "SELL"

    # -- Hard gate 2: overvalued + weak fundamentals -----------------------
    if (
        fund_data_quality != "insufficient"
        and valuation_verdict == "overvalued"
        and fund_score < 6
    ):
        return "SELL"

    # -- Weighted point tally -----------------------------------------------
    score = 0.0
    score += (fund_score - 5) * 0.4

    tech_signal = str(technical.get("signal") or "HOLD")
    tech_strength = int(technical.get("signal_strength") or 5)
    if tech_signal == "BUY":
        score += tech_strength * 0.15
    elif tech_signal == "SELL":
        score -= tech_strength * 0.15

    sent_score = float(sentiment.get("sentiment_score") or 0.0)
    score += sent_score * 1.5

    if valuation_verdict == "undervalued":
        score += 1.5
    elif valuation_verdict == "overvalued":
        score -= 1.5

    score -= max(0, risk_score - 5) * 0.35

    if bear_conviction >= _HIGH_BEAR_CONVICTION_THRESHOLD:
        score -= 1.5
    else:
        score -= (bear_conviction - 1) * 0.1

    score -= len(critical_flags) * 0.3

    if score >= 1.5:
        verdict = "BUY"
    elif score <= -1.5:
        verdict = "SELL"
    else:
        verdict = "HOLD"

    # -- Soft downgrade: marginal BUY + heavy critical flags -> HOLD ------
    if (
        verdict == "BUY"
        and len(critical_flags) >= _CRITICAL_FLAGS_DOWNGRADE_THRESHOLD
        and score < 3.0
    ):
        verdict = "HOLD"

    return verdict


# ---------------------------------------------------------------------------
# Stage 1c -- conviction (quality of analysis, not strength of signal)
# ---------------------------------------------------------------------------


def _signal_direction(value: float, threshold: float = 0.15) -> int:
    """Map a continuous value to -1 / 0 / +1 around a dead-zone threshold."""
    if value > threshold:
        return 1
    if value < -threshold:
        return -1
    return 0


def _score_conviction(
    fundamental: dict[str, Any],
    technical: dict[str, Any],
    sentiment: dict[str, Any],
    macro: dict[str, Any],
    risk: dict[str, Any],
    contrarian: dict[str, Any],
    valuation: dict[str, Any],
    verdict: str,
    debate_rounds_used: int,
) -> int:
    """
    Score conviction (1-10) based on the QUALITY of the analysis that
    produced the verdict, not on how strongly bullish or bearish any
    individual signal is. A clean, agreeing, low-risk, single-round
    profile scores higher conviction than a conflicting, high-risk,
    multi-round profile -- even when both resolve to the same verdict.
    """
    conviction = 5.0

    fund_score = int(fundamental.get("score") or 5)
    tech_signal = str(technical.get("signal") or "HOLD")
    sent_score = float(sentiment.get("sentiment_score") or 0.0)
    valuation_verdict = str(valuation.get("valuation_verdict") or "fairly_valued")

    fund_dir = _signal_direction(fund_score - 5)
    tech_dir = 1 if tech_signal == "BUY" else (-1 if tech_signal == "SELL" else 0)
    sent_dir = _signal_direction(sent_score)
    val_dir = (
        1
        if valuation_verdict == "undervalued"
        else (-1 if valuation_verdict == "overvalued" else 0)
    )

    directions = [d for d in (fund_dir, tech_dir, sent_dir, val_dir) if d != 0]
    if directions:
        agreement_ratio = sum(1 for d in directions if d == directions[0]) / len(
            directions
        )
        if agreement_ratio >= 0.75 and len(directions) >= 3:
            conviction += 2.0
        elif agreement_ratio <= 0.4:
            conviction -= 2.0

        if verdict == "HOLD" and len(set(directions)) > 1:
            conviction = min(conviction, 5.0)

    bear_conviction = int(contrarian.get("bear_conviction") or 1)
    if bear_conviction >= _HIGH_BEAR_CONVICTION_THRESHOLD:
        conviction -= 2.0
    elif bear_conviction <= 3:
        conviction += 1.0

    error_count = sum(
        1
        for out in (fundamental, technical, sentiment, macro, risk, valuation)
        if not out or out.get("error")
    )
    conviction -= error_count * 1.0

    critical_flags_count = len(risk.get("critical_flags") or [])
    conviction -= critical_flags_count * 0.5

    if debate_rounds_used >= 2:
        conviction -= 1.0

    return max(1, min(10, round(conviction)))


# ---------------------------------------------------------------------------
# Stage 1d -- time horizon
# ---------------------------------------------------------------------------


def _determine_time_horizon(
    technical: dict[str, Any],
    valuation: dict[str, Any],
    verdict: str,
) -> str:
    """Choose a holding-period phrase based on what is driving the verdict."""
    if verdict == "HOLD":
        return "quarterly review (3 months)"

    tech_strength = int(technical.get("signal_strength") or 5)
    margin_of_safety = str(valuation.get("margin_of_safety") or "low")

    if tech_strength >= 8:
        return "3-6 months (technically driven, reassess on momentum shift)"

    if verdict == "BUY" and margin_of_safety == "high":
        return "3-5 years (high margin of safety supports a long hold)"

    return "12 months"


# ---------------------------------------------------------------------------
# Stage 1e -- price target
# ---------------------------------------------------------------------------


def _build_price_target(valuation: dict[str, Any], time_horizon: str) -> Optional[str]:
    """Format the DCF intrinsic value into a price-target string."""
    intrinsic = valuation.get("intrinsic_value_per_share")
    if intrinsic is None:
        return None
    try:
        intrinsic_float = float(intrinsic)
    except (TypeError, ValueError):
        return None
    return f"Rs. {intrinsic_float:,.0f} ({time_horizon})"


# ---------------------------------------------------------------------------
# Stage 1f -- key_risks / key_catalysts
# ---------------------------------------------------------------------------


def _build_key_risks(
    risk: dict[str, Any],
    contrarian: dict[str, Any],
    critical_flags: list[str],
) -> list[str]:
    """
    Structured risk list: Risk Officer's critical_flags first (it already
    applied its own severity judgement), then the Contrarian's strongest
    argument and overlooked risks, then any remaining state-level
    critical flags. De-duplicated, capped at _MAX_KEY_RISKS.
    """
    risks: list[str] = []
    seen: set[str] = set()

    def _add(item: Any) -> None:
        text = str(item).strip()
        if text and text not in seen:
            risks.append(text)
            seen.add(text)

    for flag in risk.get("critical_flags") or []:
        _add(flag)

    strongest = contrarian.get("strongest_argument")
    if strongest:
        _add(strongest)

    for overlooked in contrarian.get("overlooked_risks") or []:
        _add(overlooked)

    for flag in critical_flags or []:
        _add(flag)

    if not risks:
        risks.append(
            "No critical risk flags identified; monitor standard "
            "execution and market risk."
        )

    return risks[:_MAX_KEY_RISKS]


def _build_key_catalysts(
    macro: dict[str, Any],
    fundamental: dict[str, Any],
    valuation: dict[str, Any],
) -> list[str]:
    """
    Structured catalyst list: macro tailwinds, a DCF-upside re-rating
    catalyst (when margin of safety supports it), macro headwinds framed
    as items to monitor, and fundamental strengths. Capped at
    _MAX_KEY_CATALYSTS.
    """
    catalysts: list[str] = []
    seen: set[str] = set()

    def _add(item: Any) -> None:
        text = str(item).strip()
        if text and text not in seen:
            catalysts.append(text)
            seen.add(text)

    for tailwind in macro.get("tailwinds") or []:
        _add(tailwind)

    margin_of_safety = valuation.get("margin_of_safety")
    if margin_of_safety in ("high", "moderate"):
        upside = valuation.get("upside_downside_pct")
        upside_text = f"{upside:.1f}%" if isinstance(upside, (int, float)) else "the"
        _add(
            f"DCF implies {upside_text} upside to intrinsic value -- a "
            "re-rating catalyst if the market closes the gap."
        )

    for headwind in (macro.get("headwinds") or [])[:1]:
        _add(f"Monitor: {headwind}")

    for strength in (fundamental.get("strengths") or [])[:2]:
        _add(strength)

    if not catalysts:
        catalysts.append(
            "No specific near-term catalysts identified; thesis depends "
            "on continued execution."
        )

    return catalysts[:_MAX_KEY_CATALYSTS]


# ---------------------------------------------------------------------------
# Stage 1g -- debate transcript highlights
# ---------------------------------------------------------------------------


def _extract_debate_highlights(debate_rounds: list[dict[str, Any]]) -> list[str]:
    """
    Convert state["debate_rounds"] into one human-readable
    "Round N: <contrarian challenge>" line per round. Grounds the LLM
    prompt in real debate content instead of letting it invent
    plausible-sounding detail.
    """
    highlights: list[str] = []
    for entry in debate_rounds or []:
        round_number = entry.get("round_number", len(highlights) + 1)
        contrarian_text = str(entry.get("contrarian") or "").strip()
        if not contrarian_text:
            contrarian_text = "no contrarian challenge recorded this round."
        highlights.append(f"Round {round_number}: {contrarian_text}")
    return highlights


# ---------------------------------------------------------------------------
# Stage 2 -- LLM prompt builder
# ---------------------------------------------------------------------------


def _build_portfolio_manager_prompt(
    company_name: str,
    ticker: str,
    fundamental: dict[str, Any],
    technical: dict[str, Any],
    sentiment: dict[str, Any],
    macro: dict[str, Any],
    risk: dict[str, Any],
    contrarian: dict[str, Any],
    valuation: dict[str, Any],
    debate_highlights: list[str],
    verdict: str,
    conviction_score: int,
    time_horizon: str,
    price_target: Optional[str],
    key_risks: list[str],
    key_catalysts: list[str],
) -> str:
    """Build the user-turn prompt handing the LLM every Stage 1 result."""
    debate_text = (
        "\n".join(f"  - {line}" for line in debate_highlights)
        if debate_highlights
        else "  (no debate rounds occurred)"
    )
    strongest_argument = contrarian.get("strongest_argument") or (
        "(Contrarian raised no specific strongest argument)"
    )
    risks_text = "\n".join(f"  - {r}" for r in key_risks) or "  (none)"
    catalysts_text = "\n".join(f"  - {c}" for c in key_catalysts) or "  (none)"

    lines = [
        f"Company: {company_name} ({ticker})",
        "",
        "DECISION ALREADY MADE (do not change these numbers):",
        f"  Verdict: {verdict}",
        f"  Conviction score: {conviction_score}/10",
        f"  Time horizon: {time_horizon}",
        f"  Price target: {price_target or 'not available'}",
        "",
        "DEBATE TRANSCRIPT HIGHLIGHTS:",
        debate_text,
        "",
        f"CONTRARIAN'S STRONGEST ARGUMENT (must be addressed): "
        f"{strongest_argument}",
        "",
        "KEY RISKS (structured list, already finalised):",
        risks_text,
        "",
        "KEY CATALYSTS (structured list, already finalised):",
        catalysts_text,
        "",
        f"Fundamental Analyst (score {fundamental.get('score', 'n/a')}/10): "
        f"{fundamental.get('summary', 'no summary available')}",
        f"Technical Analyst (signal {technical.get('signal', 'n/a')}): "
        f"{technical.get('summary', 'no summary available')}",
        f"News Sentiment (score {sentiment.get('sentiment_score', 'n/a')}): "
        f"{sentiment.get('summary', 'no summary available')}",
        f"Macro Economist ({macro.get('macro_environment', 'n/a')}): "
        f"{macro.get('summary', 'no summary available')}",
        f"Risk Officer (risk score {risk.get('risk_score', 'n/a')}/10): "
        f"{risk.get('summary', 'no summary available')}",
        f"Valuation Agent ({valuation.get('valuation_verdict', 'n/a')}): "
        f"{valuation.get('summary', 'no summary available')}",
        "",
        "Write the Investment Memo narrative sections now, following the "
        "OUTPUT SCHEMA exactly.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stage 2 -- LLM call + parsing with deterministic fallback
# ---------------------------------------------------------------------------


def _call_llm_for_narrative(prompt: str) -> Optional[dict[str, str]]:
    """
    Call the LLM and parse its JSON response. Returns None on any
    failure (LLM error, malformed JSON, missing keys) so the caller can
    fall back to a fully deterministic narrative.
    """
    try:
        llm = get_llm()
        response = llm.invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        content = str(response.content).strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:]
        parsed = json.loads(content)
        required = {
            "executive_summary",
            "investment_thesis",
            "bull_case",
            "bear_case",
            "risk_summary",
            "valuation_summary",
            "contrarian_response",
            "summary",
        }
        if not required.issubset(parsed.keys()):
            logger.warning(
                "portfolio_manager: LLM response missing required keys: %s",
                required - parsed.keys(),
            )
            return None
        return {k: str(parsed[k]) for k in required}
    except Exception as exc:  # noqa: BLE001 -- agent must never raise
        logger.warning("portfolio_manager: LLM narrative synthesis failed: %s", exc)
        return None


def _build_fallback_narrative(
    company_name: str,
    ticker: str,
    verdict: str,
    conviction_score: int,
    debate_highlights: list[str],
    contrarian: dict[str, Any],
    risk: dict[str, Any],
    valuation: dict[str, Any],
) -> dict[str, str]:
    """
    Fully deterministic narrative used when the LLM call fails or returns
    malformed JSON. Still satisfies the debate-reference and
    contrarian-response acceptance criteria without any LLM assistance.
    """
    round_ref = (
        debate_highlights[0] if debate_highlights else "Round 1: no debate occurred"
    )
    strongest_argument = contrarian.get("strongest_argument") or (
        "no specific strongest argument was raised"
    )
    risk_score = risk.get("risk_score", "n/a")
    valuation_verdict = valuation.get("valuation_verdict", "n/a")

    summary_line = (
        f"{company_name} ({ticker}): {verdict} with conviction "
        f"{conviction_score}/10."
    )

    return {
        "executive_summary": (
            f"The investment committee has reached a {verdict} decision on "
            f"{company_name} ({ticker}) with a conviction score of "
            f"{conviction_score}/10. This decision reflects a weighted "
            f"synthesis of fundamental, technical, sentiment, macro, risk, "
            f"contrarian, and valuation analysis."
        ),
        "investment_thesis": (
            f"The committee's thesis is grounded in the debate record -- "
            f"{round_ref} The final {verdict} verdict accounts for this "
            f"challenge alongside the broader weight of evidence."
        ),
        "bull_case": (
            "The bull case rests on the combined weight of fundamental, "
            "technical, and valuation signals favouring the position."
        ),
        "bear_case": (
            f"The bear case is anchored by the Contrarian's challenge: "
            f"{strongest_argument}"
        ),
        "risk_summary": (
            f"Risk Officer assessed an overall risk score of "
            f"{risk_score}/10. Key risks are detailed in the structured "
            f"risk list accompanying this decision."
        ),
        "valuation_summary": (
            f"The Valuation Agent's DCF and peer-multiple analysis "
            f"resolves to a '{valuation_verdict}' verdict on current "
            f"pricing."
        ),
        "contrarian_response": (
            f"The Contrarian's strongest argument -- {strongest_argument} "
            f"-- was directly weighed against the rest of the committee's "
            f"evidence in reaching the final {verdict} verdict."
        ),
        "summary": summary_line,
    }


# ---------------------------------------------------------------------------
# Core orchestration (both stages)
# ---------------------------------------------------------------------------


def _run_portfolio_manager_core(
    analysis_id: str,
    company_name: str,
    ticker: str,
    fundamental: Optional[dict[str, Any]],
    technical: Optional[dict[str, Any]],
    sentiment: Optional[dict[str, Any]],
    macro: Optional[dict[str, Any]],
    risk: Optional[dict[str, Any]],
    contrarian: Optional[dict[str, Any]],
    valuation: Optional[dict[str, Any]],
    debate_rounds: Optional[list[dict[str, Any]]],
    debate_round_count: int,
    critical_flags: Optional[list[str]],
) -> InvestmentDecision:
    """
    Run both stages and return a fully-populated InvestmentDecision.
    Never raises -- any failure degrades to a deterministic fallback.
    """
    fundamental = fundamental or {}
    technical = technical or {}
    sentiment = sentiment or {}
    macro = macro or {}
    risk = risk or {}
    contrarian = contrarian or {}
    valuation = valuation or {}
    debate_rounds = debate_rounds or []
    critical_flags = critical_flags or []

    debate_rounds_used = max(1, debate_round_count or len(debate_rounds) or 1)

    agent_weights = _compute_agent_weights(
        fundamental, technical, sentiment, macro, risk, contrarian, valuation
    )
    verdict = _determine_verdict(
        fundamental, technical, sentiment, risk, contrarian, valuation, critical_flags
    )
    conviction_score = _score_conviction(
        fundamental,
        technical,
        sentiment,
        macro,
        risk,
        contrarian,
        valuation,
        verdict,
        debate_rounds_used,
    )
    time_horizon = _determine_time_horizon(technical, valuation, verdict)
    price_target = _build_price_target(valuation, time_horizon)
    key_risks = _build_key_risks(risk, contrarian, critical_flags)
    key_catalysts = _build_key_catalysts(macro, fundamental, valuation)
    debate_highlights = _extract_debate_highlights(debate_rounds)

    prompt = _build_portfolio_manager_prompt(
        company_name=company_name,
        ticker=ticker,
        fundamental=fundamental,
        technical=technical,
        sentiment=sentiment,
        macro=macro,
        risk=risk,
        contrarian=contrarian,
        valuation=valuation,
        debate_highlights=debate_highlights,
        verdict=verdict,
        conviction_score=conviction_score,
        time_horizon=time_horizon,
        price_target=price_target,
        key_risks=key_risks,
        key_catalysts=key_catalysts,
    )

    narrative = _call_llm_for_narrative(prompt)
    if narrative is None:
        narrative = _build_fallback_narrative(
            company_name=company_name,
            ticker=ticker,
            verdict=verdict,
            conviction_score=conviction_score,
            debate_highlights=debate_highlights,
            contrarian=contrarian,
            risk=risk,
            valuation=valuation,
        )

    return InvestmentDecision(
        analysis_id=analysis_id,
        company_name=company_name,
        ticker=ticker,
        verdict=verdict,
        conviction_score=conviction_score,
        price_target=price_target,
        time_horizon=time_horizon,
        executive_summary=narrative["executive_summary"],
        investment_thesis=narrative["investment_thesis"],
        bull_case=narrative["bull_case"],
        bear_case=narrative["bear_case"],
        risk_summary=narrative["risk_summary"],
        valuation_summary=narrative["valuation_summary"],
        key_risks=key_risks,
        key_catalysts=key_catalysts,
        contrarian_response=narrative["contrarian_response"],
        debate_rounds_used=debate_rounds_used,
        agent_weights=agent_weights,
        summary=narrative["summary"],
    )


# ---------------------------------------------------------------------------
# LangGraph node entry point
# ---------------------------------------------------------------------------


@traced_agent("portfolio_manager")
def run_portfolio_manager_decision(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph node entry point. Reads the full InvestmentState and
    returns the partial-state update for the portfolio_manager node.
    """
    job_id = state.get("job_id", "unknown")
    company_name = state.get("company_name", "unknown")
    ticker = state.get("ticker", "")

    if not ticker:
        logger.warning("run_portfolio_manager_decision called with empty ticker")
        decision = InvestmentDecision(
            analysis_id=job_id,
            company_name=company_name,
            ticker=ticker or "unknown",
            verdict="HOLD",
            conviction_score=1,
            error="ticker field is missing from InvestmentState",
        )
        return {
            "decision": decision.model_dump(),
            "final_verdict": decision.verdict,
            "conviction_score": decision.conviction_score,
            "price_target": decision.price_target,
        }

    decision = _run_portfolio_manager_core(
        analysis_id=job_id,
        company_name=company_name,
        ticker=ticker,
        fundamental=state.get("fundamental"),
        technical=state.get("technical"),
        sentiment=state.get("sentiment"),
        macro=state.get("macro"),
        risk=state.get("risk"),
        contrarian=state.get("contrarian"),
        valuation=state.get("valuation"),
        debate_rounds=state.get("debate_rounds"),
        debate_round_count=state.get("debate_round_count", 0),
        critical_flags=state.get("critical_flags"),
    )

    return {
        "decision": decision.model_dump(),
        "final_verdict": decision.verdict,
        "conviction_score": decision.conviction_score,
        "price_target": decision.price_target,
    }


__all__ = [
    "SYSTEM_PROMPT",
    "run_portfolio_manager_decision",
    "_run_portfolio_manager_core",
    "_compute_agent_weights",
    "_determine_verdict",
    "_score_conviction",
    "_determine_time_horizon",
    "_build_price_target",
    "_build_key_risks",
    "_build_key_catalysts",
    "_extract_debate_highlights",
    "_build_portfolio_manager_prompt",
]
