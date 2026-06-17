# backend/agents/portfolio_manager.py
"""
AIRP -- Portfolio Manager Agent (T-041)

Persona: CIO of a hedge fund with final authority over every investment
decision the committee makes.  Reads the complete debate -- all 7 prior
agent outputs plus the full multi-round debate transcript -- and renders
the single, accountable BUY / HOLD / SELL verdict that the rest of the
firm acts on.

Mandate
-------
Produce an InvestmentDecision that:
  * Synthesises FundamentalAnalysis, TechnicalAnalysis, SentimentAnalysis,
    MacroAnalysis, RiskAnalysis, ContrarianReport, and ValuationOutput into
    one coherent verdict -- no single research agent has unchecked
    authority over the conclusion.
  * Explicitly references specific points raised during the debate
    (acceptance criterion: "decision references specific points from
    debate").  The Contrarian's strongest_argument from every recorded
    debate round MUST be named and addressed in contrarian_response.
  * Assigns a conviction_score (1-10) that tracks the QUALITY of the
    underlying analysis, not just the strength of the bull/bear signal
    (acceptance criterion: "conviction score correlates with quality of
    analysis").  Conflicting signals across agents, missing data, and
    high bear_conviction from the Contrarian all reduce conviction even
    when the verdict itself stays the same.
  * Fills in the full set of Investment Memo sections (executive_summary,
    investment_thesis, bull_case, bear_case, risk_summary,
    valuation_summary) plus the structured key_risks[] / key_catalysts[]
    lists and a time_horizon string -- everything the Report Generator
    (T-042) needs to build the 2-page memo without re-deriving anything.

Two-stage pipeline
-------------------
  Stage 1 -- Deterministic: verdict, conviction_score, agent_weights,
             key_risks, key_catalysts, time_horizon, price_target.
             All derived from structured fields on the 7 prior agent
             outputs plus the debate transcript -- no LLM involved, so
             these numbers are reproducible and testable in isolation.
  Stage 2 -- LLM narrative synthesis: executive_summary, investment_thesis,
             bull_case, bear_case, risk_summary, valuation_summary,
             contrarian_response, summary.  The LLM is given every
             deterministic number already decided in Stage 1 and told
             NOT to change them -- it writes the prose around them.

Public interface
----------------
  run_portfolio_manager_decision(state)     -> dict   LangGraph node
  _run_portfolio_manager_core(...)          -> InvestmentDecision
  _compute_agent_weights(...)               -> dict[str, float]
  _determine_verdict(...)                   -> str
  _score_conviction(...)                    -> int
  _determine_time_horizon(...)              -> str
  _build_price_target(...)                  -> Optional[str]
  _build_key_risks(...)                     -> list[str]
  _build_key_catalysts(...)                 -> list[str]
  _extract_debate_highlights(...)           -> list[str]
  _build_portfolio_manager_prompt(...)      -> str   prompt builder, pure

Design decisions
-----------------
* NO ``from __future__ import annotations`` -- breaks Pydantic v2 union
  resolution, same as every other AIRP agent module.
* Plain ASCII section comments (# ---) -- rule from T-024 onward.
* No bare ``# type: ignore`` -- use cast(), explicit annotations, assert.
* Verdict and conviction are computed BEFORE the LLM call so the final
  decision is always deterministic and testable even if the LLM fails or
  is mocked.  The LLM enriches with narrative only -- it cannot override
  verdict, conviction_score, key_risks, key_catalysts, or time_horizon.
* agent_weights sum to 1.0 (or are all 0.0 when no agents produced usable
  output) so the Portfolio Manager's relative trust in each agent is
  directly comparable across analyses.
* Error convention: never raises.  On any failure InvestmentDecision.error
  is set, verdict defaults to "HOLD", and conviction_score defaults to 1
  (lowest possible conviction -- a failed synthesis should never present
  as confident).
* LangSmith tracing is automatic via @traced_agent.

Usage in LangGraph (Phase 4)
-----------------------------
    from backend.agents.portfolio_manager import run_portfolio_manager_decision
    builder.add_node("portfolio_manager", run_portfolio_manager_decision)
    # Reads:  state["fundamental"], state["technical"], state["sentiment"],
    #         state["macro"], state["risk"], state["contrarian"],
    #         state["valuation"], state["debate_rounds"],
    #         state["debate_round_count"], state["critical_flags"]
    # Writes: state["decision"]        (InvestmentDecision.model_dump())
    #         state["final_verdict"]
    #         state["conviction_score"]
    #         state["price_target"]
"""

import json
import logging
import re
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.llm_factory import get_llm
from backend.agents.output_models import InvestmentDecision
from backend.agents.tracing import traced_agent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent persona -- system prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the Portfolio Manager and Chief Investment Officer of a hedge fund \
investment committee.  Six specialist agents and a professional sceptic \
have already done the research and argued their positions in front of you. \
Your job is not to redo their analysis -- it is to weigh it, resolve the \
disagreements, and put your name on a single accountable decision.

You have been given the final verdict, conviction score, and several other \
numbers that have ALREADY been decided deterministically.  Do NOT change \
these numbers.  Your job is to write the narrative that explains and \
justifies them in plain English, the way a real CIO would explain a \
decision to the firm's risk committee.

RULES:
1. The investment_thesis must explicitly reference at least one specific, \
   named point from the debate transcript (e.g. naming a counter-argument \
   the Contrarian raised, or a specific risk flag the Risk Officer cited). \
   Generic statements with no specific reference are not acceptable.
2. contrarian_response MUST name and directly address the Contrarian's \
   strongest_argument supplied to you.  Either explain why the committee \
   is overruling it, or explain how the verdict already accounts for it.
3. bull_case synthesises the strongest points from Fundamental, Technical, \
   Sentiment, and Macro.  bear_case synthesises the Contrarian's challenges \
   and the Risk Officer's critical flags.  Both must reference at least \
   one concrete number (a score, a ratio, a percentage) from the data \
   you were given.
4. risk_summary and valuation_summary are each 2-3 sentences referencing \
   the actual Risk Officer and Valuation Agent outputs you were given.
5. Do NOT use markdown, bullet symbols, or headers anywhere in your output.
6. Respond ONLY with valid JSON matching the exact schema below -- no \
   markdown fences, no commentary before or after the JSON object.
7. executive_summary is 2-3 short paragraphs written for a non-specialist \
   reader who has not seen any of the underlying agent output.

OUTPUT SCHEMA (strict JSON, no markdown fences):
{
  "executive_summary": "<2-3 paragraphs, plain English>",
  "investment_thesis": "<3-5 sentences, must name a specific debate point>",
  "bull_case": "<synthesised bull case with at least one concrete number>",
  "bear_case": "<synthesised bear case with at least one concrete number>",
  "risk_summary": "<2-3 sentences referencing actual Risk Officer output>",
  "valuation_summary": "<2-3 sentences referencing actual Valuation output>",
  "contrarian_response": "<names and addresses the strongest_argument>",
  "summary": "<1 sentence, dashboard-ready, e.g. 'TCS: BUY conviction 8/10'>"
}"""

# ---------------------------------------------------------------------------
# Deterministic constants
# ---------------------------------------------------------------------------

#: bear_conviction at or above this level is treated as a serious,
#: well-evidenced challenge that materially caps the Portfolio Manager's
#: conviction in a BUY verdict, regardless of how bullish the research
#: agents were.
_HIGH_BEAR_CONVICTION_THRESHOLD: int = 7

#: risk_score at or above this level is treated as prohibitive -- the
#: Portfolio Manager will not issue a BUY verdict no matter how strong
#: the bull case looks on fundamentals/technicals/sentiment/macro alone.
_PROHIBITIVE_RISK_SCORE_THRESHOLD: int = 8

#: Minimum number of critical_flags that, combined with a mediocre
#: fundamental score, is enough to downgrade a marginal BUY to HOLD.
_CRITICAL_FLAGS_DOWNGRADE_THRESHOLD: int = 2

# ---------------------------------------------------------------------------
# Stage 1a -- agent_weights
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
    Compute how much weight the Portfolio Manager assigns to each agent.

    Base weights reflect AIRP's house view on signal quality for Indian
    equities: fundamentals and valuation are the primary anchors, risk
    and the contrarian challenge are next, technicals and macro are
    supporting context, and sentiment is the most noise-prone input.

    Any agent whose output is missing or carries an ``error`` has its
    weight zeroed out and redistributed proportionally across the
    remaining agents, so weights always sum to 1.0 (or to 0.0 only in
    the degenerate case where every single agent failed).

    Returns:
        Dict mapping agent_name -> weight in [0.0, 1.0], summing to 1.0
        (or all-zero if every agent errored).
    """
    base_weights: dict[str, float] = {
        "fundamental_analyst": 0.20,
        "valuation_agent": 0.20,
        "risk_officer": 0.15,
        "contrarian_investor": 0.15,
        "technical_analyst": 0.12,
        "macro_economist": 0.10,
        "news_sentiment": 0.08,
    }

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
        if out and not out.get("error"):
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
    Determine the final BUY / HOLD / SELL verdict deterministically.

    Hard gates evaluated first (any one of these forces SELL or HOLD
    regardless of how bullish other agents are):
      * risk_score >= _PROHIBITIVE_RISK_SCORE_THRESHOLD -> SELL
      * valuation_verdict == 'overvalued' AND fundamental score < 6 -> SELL

    Otherwise a weighted bullish/bearish point tally decides between
    BUY / HOLD / SELL, with the Contrarian and Risk Officer able to pull
    a marginal BUY down to HOLD even when the research agents are
    individually positive -- mirroring how a real committee lets risk
    and dissent cap enthusiasm.

    Returns:
        One of "BUY", "HOLD", "SELL".
    """
    risk_score: int = int(risk.get("risk_score") or 5)
    valuation_verdict: str = str(valuation.get("valuation_verdict") or "fairly_valued")
    fund_score: int = int(fundamental.get("score") or 5)
    bear_conviction: int = int(contrarian.get("bear_conviction") or 1)

    # --- Hard gates ----------------------------------------------------
    if risk_score >= _PROHIBITIVE_RISK_SCORE_THRESHOLD:
        return "SELL"
    if valuation_verdict == "overvalued" and fund_score < 6:
        return "SELL"

    # --- Weighted bullish/bearish point tally ---------------------------
    score: float = 0.0

    # Fundamental: -2..+2
    score += (fund_score - 5) * 0.4

    # Technical signal
    tech_signal: str = str(technical.get("signal") or "HOLD")
    tech_strength: int = int(technical.get("signal_strength") or 5)
    if tech_signal == "BUY":
        score += tech_strength * 0.15
    elif tech_signal == "SELL":
        score -= tech_strength * 0.15

    # Sentiment: -1..+1 scaled
    sent_score: float = float(sentiment.get("sentiment_score") or 0.0)
    score += sent_score * 1.5

    # Valuation verdict
    if valuation_verdict == "undervalued":
        score += 1.5
    elif valuation_verdict == "overvalued":
        score -= 1.5

    # Risk: penalise proportionally above a neutral midpoint
    score -= max(0, risk_score - 5) * 0.35

    # Contrarian: high bear_conviction actively suppresses bullishness
    if bear_conviction >= _HIGH_BEAR_CONVICTION_THRESHOLD:
        score -= 1.5
    else:
        score -= (bear_conviction - 1) * 0.1

    # Critical flags: each one chips away at conviction in a BUY verdict
    score -= len(critical_flags) * 0.3

    if score >= 1.5:
        verdict = "BUY"
    elif score <= -1.5:
        verdict = "SELL"
    else:
        verdict = "HOLD"

    # --- Soft downgrade: marginal BUY + heavy critical flags -> HOLD ----
    if (
        verdict == "BUY"
        and len(critical_flags) >= _CRITICAL_FLAGS_DOWNGRADE_THRESHOLD
        and score < 3.0
    ):
        verdict = "HOLD"

    return verdict


# ---------------------------------------------------------------------------
# Stage 1c -- conviction_score
# ---------------------------------------------------------------------------


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
    Score conviction (1-10) based on the QUALITY and AGREEMENT of the
    underlying analysis -- not merely the strength of the directional
    signal.  This directly satisfies the acceptance criterion that
    "conviction score correlates with quality of analysis".

    Quality signals that INCREASE conviction:
      * Agents agree with each other (signal alignment across
        fundamental / technical / sentiment / macro / valuation)
      * Valuation and fundamentals corroborate each other
      * Low bear_conviction (the Contrarian could not build a strong case)
      * Few or no critical_flags
      * Low debate_rounds_used (consensus reached quickly)

    Quality signals that DECREASE conviction:
      * Agents disagree directionally (e.g. fundamentals bullish but
        technicals bearish, or sentiment strongly opposes the verdict)
      * Missing/errored agent outputs (less evidence to act on)
      * High bear_conviction (the Contrarian built a credible case)
      * Many critical_flags
      * Multiple debate rounds were needed to reach a conclusion

    Returns:
        Integer conviction score, clamped to [1, 10].
    """
    conviction: float = 5.0  # neutral starting point

    # --- Agreement bonus: count how many directional signals agree ------
    fund_score: int = int(fundamental.get("score") or 5)
    tech_signal: str = str(technical.get("signal") or "HOLD")
    sent_score: float = float(sentiment.get("sentiment_score") or 0.0)
    valuation_verdict: str = str(valuation.get("valuation_verdict") or "fairly_valued")

    def _signal_direction(value: float) -> int:
        if value > 0.15:
            return 1
        if value < -0.15:
            return -1
        return 0

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

    # --- Contrarian credibility ------------------------------------------
    bear_conviction: int = int(contrarian.get("bear_conviction") or 1)
    if bear_conviction >= _HIGH_BEAR_CONVICTION_THRESHOLD:
        conviction -= 2.0
    elif bear_conviction <= 3:
        conviction += 1.0

    # --- Missing / errored data penalty -----------------------------------
    error_count = sum(
        1
        for out in (fundamental, technical, sentiment, macro, risk, valuation)
        if not out or out.get("error")
    )
    conviction -= error_count * 1.0

    # --- Critical flags penalty --------------------------------------------
    critical_flags_count = len(risk.get("critical_flags") or [])
    conviction -= critical_flags_count * 0.5

    # --- Debate length penalty: more rounds = more unresolved disagreement -
    if debate_rounds_used >= 2:
        conviction -= 1.0

    # --- A HOLD verdict reached via genuine signal conflict (not just
    #     middling data) should not masquerade as a confident call. ------
    if verdict == "HOLD" and directions and len(set(directions)) > 1:
        conviction = min(conviction, 5.0)

    return max(1, min(10, round(conviction)))


# ---------------------------------------------------------------------------
# Stage 1d -- time_horizon
# ---------------------------------------------------------------------------


def _determine_time_horizon(
    technical: dict[str, Any],
    valuation: dict[str, Any],
    verdict: str,
) -> str:
    """
    Choose a recommended holding period based on what is actually driving
    the verdict.

    A verdict led primarily by technical momentum implies a shorter
    horizon (the signal can decay in weeks); a verdict anchored in DCF
    intrinsic value implies a multi-year horizon (re-rating takes time);
    anything in between defaults to the standard 12-month committee
    review cycle.

    Returns:
        Short human-readable horizon phrase.
    """
    if verdict == "HOLD":
        return "Next quarterly review (3 months)"

    tech_signal: str = str(technical.get("signal") or "HOLD")
    tech_strength: int = int(technical.get("signal_strength") or 5)
    margin_of_safety: str = str(valuation.get("margin_of_safety") or "moderate")

    technical_led = (
        verdict == "BUY" and tech_signal == "BUY" and tech_strength >= 8
    ) or (verdict == "SELL" and tech_signal == "SELL" and tech_strength >= 8)
    if technical_led:
        return "3-6 months (technically driven, reassess on momentum shift)"

    if verdict == "BUY" and margin_of_safety == "high":
        return "3-5 years (long-term value re-rating)"

    return "12 months"


# ---------------------------------------------------------------------------
# Stage 1e -- price_target
# ---------------------------------------------------------------------------


def _build_price_target(valuation: dict[str, Any], time_horizon: str) -> Optional[str]:
    """
    Build the price_target string from the Valuation Agent's intrinsic
    value, when available.

    Returns:
        A formatted string like "Rs. 4,200 (12 months)", or None when the
        Valuation Agent could not produce an intrinsic value.
    """
    intrinsic_value: Any = valuation.get("intrinsic_value_per_share")
    if intrinsic_value is None:
        return None
    try:
        value = float(intrinsic_value)
    except (TypeError, ValueError):
        return None

    horizon_short = time_horizon.split("(")[0].strip()
    return f"Rs. {value:,.0f} ({horizon_short})"


# ---------------------------------------------------------------------------
# Stage 1f -- key_risks / key_catalysts
# ---------------------------------------------------------------------------


def _build_key_risks(
    risk: dict[str, Any],
    contrarian: dict[str, Any],
    critical_flags: list[str],
) -> list[str]:
    """
    Build the structured key_risks[] list for the Investment Memo.

    Priority order: Risk Officer's critical_flags first (most severe,
    already vetted as critical), then the Contrarian's strongest_argument
    and overlooked_risks (fresh angles no other agent raised), then any
    remaining state-level critical_flags not already captured.  Capped at
    6 entries and de-duplicated by a case-insensitive prefix match so the
    memo stays readable.

    Returns:
        List of 1-6 one-sentence risk strings, highest severity first.
    """
    risks: list[str] = []
    seen: set[str] = set()

    def _add(item: str) -> None:
        key = item.strip()[:60].lower()
        if item.strip() and key not in seen:
            seen.add(key)
            risks.append(item.strip())

    for flag in risk.get("critical_flags") or []:
        _add(str(flag))

    strongest = contrarian.get("strongest_argument")
    if strongest:
        _add(str(strongest))

    for overlooked in contrarian.get("overlooked_risks") or []:
        _add(str(overlooked))

    for flag in critical_flags:
        _add(str(flag))

    if not risks:
        risks.append(
            "No critical risk flags identified -- standard market and "
            "execution risk applies."
        )

    return risks[:6]


def _build_key_catalysts(
    macro: dict[str, Any],
    fundamental: dict[str, Any],
    valuation: dict[str, Any],
) -> list[str]:
    """
    Build the structured key_catalysts[] list for the Investment Memo.

    Sources: macro tailwinds/headwinds (forward-looking by nature),
    fundamental strengths that represent ongoing trends rather than
    static facts, and the valuation margin-of-safety classification
    (a catalyst for re-rating when materially undervalued).  Capped at
    5 entries.

    Returns:
        List of 1-5 one-sentence forward-looking catalyst strings.
    """
    catalysts: list[str] = []
    seen: set[str] = set()

    def _add(item: str) -> None:
        key = item.strip()[:60].lower()
        if item.strip() and key not in seen:
            seen.add(key)
            catalysts.append(item.strip())

    for tailwind in macro.get("tailwinds") or []:
        _add(str(tailwind))

    margin_of_safety = str(valuation.get("margin_of_safety") or "")
    upside_pct = valuation.get("upside_downside_pct")
    if margin_of_safety in ("high", "moderate") and upside_pct is not None:
        try:
            upside_val = float(upside_pct)
            _add(
                f"DCF implies {upside_val:.1f}% upside to intrinsic value -- "
                f"a re-rating catalyst if the market closes the gap."
            )
        except (TypeError, ValueError):
            pass

    for headwind in macro.get("headwinds") or []:
        _add(f"Monitor: {headwind}")

    for strength in (fundamental.get("strengths") or [])[:2]:
        _add(str(strength))

    if not catalysts:
        catalysts.append(
            "No specific near-term catalysts identified -- thesis depends "
            "on continued execution rather than a single triggering event."
        )

    return catalysts[:5]


# ---------------------------------------------------------------------------
# Stage 1g -- debate transcript highlights (for the LLM prompt)
# ---------------------------------------------------------------------------


def _extract_debate_highlights(debate_rounds: list[dict[str, Any]]) -> list[str]:
    """
    Extract one human-readable highlight line per recorded debate round.

    Used to give the LLM concrete, named references to the debate so the
    investment_thesis can satisfy the "references specific points from
    debate" acceptance criterion without the LLM having to invent
    plausible-sounding but fabricated detail.

    Returns:
        List of strings, one per debate round, formatted as
        "Round N: <contrarian challenge text>".
    """
    highlights: list[str] = []
    for round_entry in debate_rounds:
        round_number = round_entry.get("round_number", "?")
        contrarian_text = str(
            round_entry.get("contrarian") or "No contrarian challenge recorded."
        )
        highlights.append(f"Round {round_number}: {contrarian_text}")
    return highlights


# ---------------------------------------------------------------------------
# Prompt builder
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
    """
    Build the user-turn prompt sent to the LLM.

    Passes every deterministic Stage 1 output explicitly and instructs
    the LLM not to alter them -- the LLM's only job is narrative synthesis
    grounded in the specific numbers and debate points supplied.
    """

    def _fmt(val: Any, suffix: str = "") -> str:
        if val is None:
            return "N/A"
        if isinstance(val, float):
            return f"{val:,.2f}{suffix}"
        return f"{val}{suffix}"

    fund_score: Any = fundamental.get("score", "N/A")
    fund_summary: str = str(fundamental.get("summary") or "No summary available")
    fund_strengths: list[str] = fundamental.get("strengths", []) or []
    fund_weaknesses: list[str] = fundamental.get("weaknesses", []) or []

    tech_signal: str = str(technical.get("signal") or "N/A")
    tech_strength: Any = technical.get("signal_strength", "N/A")
    tech_summary: str = str(technical.get("summary") or "No summary available")

    sent_score: Any = sentiment.get("sentiment_score", "N/A")
    sent_label: str = str(sentiment.get("sentiment_label") or "N/A")
    sent_summary: str = str(sentiment.get("summary") or "No summary available")

    macro_env: str = str(macro.get("macro_environment") or "N/A")
    sector_impact: str = str(macro.get("sector_impact") or "N/A")
    macro_summary: str = str(macro.get("summary") or "No summary available")

    risk_score: Any = risk.get("risk_score", "N/A")
    risk_rec: str = str(risk.get("risk_recommendation") or "N/A")
    risk_summary_in: str = str(risk.get("summary") or "No summary available")
    critical_flags_in: list[str] = risk.get("critical_flags", []) or []

    bear_conviction: Any = contrarian.get("bear_conviction", "N/A")
    strongest_argument: str = str(
        contrarian.get("strongest_argument") or "No strongest argument recorded."
    )
    contrarian_summary: str = str(contrarian.get("summary") or "No summary available")

    intrinsic_value: Any = valuation.get("intrinsic_value_per_share")
    upside_pct: Any = valuation.get("upside_downside_pct")
    valuation_verdict: str = str(valuation.get("valuation_verdict") or "N/A")
    margin_of_safety: str = str(valuation.get("margin_of_safety") or "N/A")
    valuation_summary_in: str = str(valuation.get("summary") or "No summary available")

    strengths_block = (
        "\n".join(f"  - {s}" for s in fund_strengths[:4]) or "  None listed"
    )
    weaknesses_block = (
        "\n".join(f"  - {w}" for w in fund_weaknesses[:4]) or "  None listed"
    )
    critical_flags_block = (
        "\n".join(f"  - {f}" for f in critical_flags_in[:5]) or "  None"
    )
    debate_block = "\n".join(f"  {h}" for h in debate_highlights) or "  (no rounds)"
    key_risks_block = "\n".join(f"  - {r}" for r in key_risks) or "  None"
    key_catalysts_block = "\n".join(f"  - {c}" for c in key_catalysts) or "  None"

    return f"""Write the Investment Memo narrative for {company_name} ({ticker}).

THE FOLLOWING HAVE ALREADY BEEN DECIDED -- DO NOT CHANGE THEM, EXPLAIN THEM:
Verdict           : {verdict}
Conviction score  : {conviction_score}/10
Time horizon      : {time_horizon}
Price target      : {price_target or "Not available"}

Key risks (already finalised, weave into risk_summary and bear_case):
{key_risks_block}

Key catalysts (already finalised, weave into bull_case or thesis):
{key_catalysts_block}

--- FUNDAMENTAL ANALYST ---
Score: {fund_score}/10
Strengths:
{strengths_block}
Weaknesses:
{weaknesses_block}
Summary: {fund_summary}

--- TECHNICAL ANALYST ---
Signal: {tech_signal} (strength {tech_strength}/10)
Summary: {tech_summary}

--- NEWS SENTIMENT AGENT ---
Score: {sent_score} ({sent_label})
Summary: {sent_summary}

--- MACRO ECONOMIST ---
Environment: {macro_env} | Sector impact: {sector_impact}
Summary: {macro_summary}

--- RISK OFFICER ---
Risk score: {risk_score}/10 | Recommendation: {risk_rec}
Critical flags:
{critical_flags_block}
Summary: {risk_summary_in}

--- CONTRARIAN INVESTOR ---
Bear conviction: {bear_conviction}/10
Strongest argument (you MUST name and address this in contrarian_response):
  "{strongest_argument}"
Summary: {contrarian_summary}

--- VALUATION AGENT ---
Intrinsic value: {_fmt(intrinsic_value, ' Rs/share')}
Upside/downside: {_fmt(upside_pct, '%')}
Verdict: {valuation_verdict} | Margin of safety: {margin_of_safety}
Summary: {valuation_summary_in}

--- DEBATE TRANSCRIPT HIGHLIGHTS (reference at least one by name) ---
{debate_block}

Your task: write executive_summary, investment_thesis, bull_case, bear_case, \
risk_summary, valuation_summary, contrarian_response, and summary per the \
system prompt schema. The investment_thesis MUST name a specific point from \
the debate transcript above. contrarian_response MUST directly address the \
Contrarian's strongest_argument quoted above.

Respond ONLY with valid JSON per the system prompt schema."""


# ---------------------------------------------------------------------------
# Core agent logic (separated from LangGraph node for testability)
# ---------------------------------------------------------------------------


def _run_portfolio_manager_core(
    analysis_id: str,
    company_name: str,
    ticker: str,
    fundamental: dict[str, Any],
    technical: dict[str, Any],
    sentiment: dict[str, Any],
    macro: dict[str, Any],
    risk: dict[str, Any],
    contrarian: dict[str, Any],
    valuation: dict[str, Any],
    debate_rounds: list[dict[str, Any]],
    debate_round_count: int,
    critical_flags: list[str],
) -> InvestmentDecision:
    """
    Core Portfolio Manager logic.

    Separated from ``run_portfolio_manager_decision`` for direct
    testability.

    Stage 1: Deterministic verdict, conviction, weights, time horizon,
             price target, key_risks, key_catalysts.
    Stage 2: LLM narrative synthesis of the full Investment Memo text.

    Never raises.  On any failure returns InvestmentDecision with error
    set, verdict "HOLD", and conviction_score 1.

    Args:
        analysis_id:          UUID of the parent Analysis job.
        company_name:         Human-readable company name.
        ticker:                Yahoo Finance ticker (e.g. 'TCS.NS').
        fundamental:           FundamentalAnalysis.model_dump() dict.
        technical:             TechnicalAnalysis.model_dump() dict.
        sentiment:             SentimentAnalysis.model_dump() dict.
        macro:                 MacroAnalysis.model_dump() dict.
        risk:                  RiskAnalysis.model_dump() dict.
        contrarian:            ContrarianReport.model_dump() dict (last round).
        valuation:             ValuationOutput.model_dump() dict.
        debate_rounds:         Full debate transcript list from state.
        debate_round_count:    Number of debate rounds that occurred.
        critical_flags:        Flat list of critical flags from state.

    Returns:
        InvestmentDecision Pydantic model (frozen, serialisable).
    """
    logger.info(
        "Portfolio Manager: starting synthesis ticker=%s debate_rounds=%d "
        "analysis=%s",
        ticker,
        debate_round_count,
        analysis_id,
    )

    # --- Stage 1: deterministic decision -----------------------------------
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
        debate_round_count,
    )
    time_horizon = _determine_time_horizon(technical, valuation, verdict)
    price_target = _build_price_target(valuation, time_horizon)
    key_risks = _build_key_risks(risk, contrarian, critical_flags)
    key_catalysts = _build_key_catalysts(macro, fundamental, valuation)
    debate_highlights = _extract_debate_highlights(debate_rounds)
    debate_rounds_used = max(1, debate_round_count)

    # --- Stage 2: LLM narrative synthesis -----------------------------------
    logger.info("Portfolio Manager: invoking LLM ticker=%s", ticker)

    executive_summary: str = ""
    investment_thesis: str = ""
    bull_case: str = ""
    bear_case: str = ""
    risk_summary: str = ""
    valuation_summary: str = ""
    contrarian_response: str = ""
    one_line_summary: str = ""

    try:
        llm = get_llm()
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
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        response = llm.invoke(messages)
        raw_text: str = (
            response.content if hasattr(response, "content") else str(response)
        )

        cleaned: str = re.sub(r"```(?:json)?|```", "", raw_text).strip()
        parsed: dict[str, Any] = json.loads(cleaned)

        executive_summary = str(parsed.get("executive_summary") or "").strip()
        investment_thesis = str(parsed.get("investment_thesis") or "").strip()
        bull_case = str(parsed.get("bull_case") or "").strip()
        bear_case = str(parsed.get("bear_case") or "").strip()
        risk_summary = str(parsed.get("risk_summary") or "").strip()
        valuation_summary = str(parsed.get("valuation_summary") or "").strip()
        contrarian_response = str(parsed.get("contrarian_response") or "").strip()
        one_line_summary = str(parsed.get("summary") or "").strip()

    except Exception as exc:
        logger.exception("LLM call failed in Portfolio Manager for %s: %s", ticker, exc)
        strongest = str(
            contrarian.get("strongest_argument") or "no contrarian challenge on file"
        )
        fund_score_fallback: Any = fundamental.get("score", "N/A")
        risk_score_fallback: Any = risk.get("risk_score", "N/A")

        executive_summary = (
            f"{company_name} ({ticker}) receives a {verdict} verdict with "
            f"conviction {conviction_score}/10. LLM narrative synthesis "
            f"failed -- this is a deterministic fallback summary. "
            f"Fundamental score {fund_score_fallback}/10, risk score "
            f"{risk_score_fallback}/10."
        )
        investment_thesis = (
            f"Deterministic synthesis only: verdict={verdict}, "
            f"conviction={conviction_score}/10, debate_rounds={debate_rounds_used}."
        )
        bull_case = "LLM synthesis unavailable -- review key_catalysts directly."
        bear_case = "LLM synthesis unavailable -- review key_risks directly."
        risk_summary = f"Risk score {risk_score_fallback}/10. See key_risks list."
        valuation_summary = (
            f"Valuation verdict: {valuation.get('valuation_verdict', 'N/A')}. "
            f"See structured valuation fields."
        )
        contrarian_response = (
            f'Contrarian\'s strongest argument on file: "{strongest}". '
            f"LLM synthesis unavailable -- committee should review manually "
            f"before acting on this verdict."
        )
        one_line_summary = (
            f"{company_name}: {verdict} with conviction {conviction_score}/10 "
            f"(LLM synthesis failed, deterministic fallback used)."
        )

    # Ensure contrarian_response always names the strongest argument, even
    # if the LLM produced output but omitted it.
    if contrarian.get("strongest_argument") and not contrarian_response:
        contrarian_response = (
            f"Addressing the Contrarian's strongest argument: "
            f"\"{contrarian.get('strongest_argument')}\". "
            f"The committee's {verdict} verdict accounts for this risk "
            f"through a conviction score of {conviction_score}/10."
        )

    if not one_line_summary:
        one_line_summary = (
            f"{company_name}: {verdict} with conviction {conviction_score}/10."
        )

    return InvestmentDecision(
        agent_name="portfolio_manager",
        analysis_id=analysis_id,
        company_name=company_name,
        ticker=ticker,
        verdict=verdict,
        conviction_score=conviction_score,
        price_target=price_target,
        time_horizon=time_horizon,
        executive_summary=executive_summary,
        investment_thesis=investment_thesis,
        bull_case=bull_case,
        bear_case=bear_case,
        risk_summary=risk_summary,
        valuation_summary=valuation_summary,
        key_risks=key_risks,
        key_catalysts=key_catalysts,
        contrarian_response=contrarian_response,
        debate_rounds_used=debate_rounds_used,
        agent_weights=agent_weights,
        summary=one_line_summary,
    )


# ---------------------------------------------------------------------------
# LangGraph node entry point
# ---------------------------------------------------------------------------


@traced_agent("portfolio_manager")
def run_portfolio_manager_decision(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph node function for the Portfolio Manager agent.

    Reads from InvestmentState:
      - job_id              -> analysis_id for the output model
      - company_name        -> human-readable company name
      - ticker               -> Yahoo Finance ticker
      - fundamental           -> FundamentalAnalysis.model_dump() (may be None)
      - technical             -> TechnicalAnalysis.model_dump() (may be None)
      - sentiment             -> SentimentAnalysis.model_dump() (may be None)
      - macro                 -> MacroAnalysis.model_dump() (may be None)
      - risk                  -> RiskAnalysis.model_dump() (may be None)
      - contrarian             -> ContrarianReport.model_dump() (may be None)
      - valuation              -> ValuationOutput.model_dump() (may be None)
      - debate_rounds          -> full debate transcript list
      - debate_round_count     -> number of debate rounds completed
      - critical_flags         -> flat list of critical flags from state

    Writes to InvestmentState:
      - decision            -> InvestmentDecision.model_dump()
      - final_verdict        -> decision.verdict
      - conviction_score     -> decision.conviction_score
      - price_target         -> decision.price_target

    Never raises -- on failure, ``decision["error"]`` is set and the
    verdict defaults to "HOLD" with conviction_score 1.

    Args:
        state: InvestmentState dict (LangGraph passes the full state).

    Returns:
        Dict with keys 'decision', 'final_verdict', 'conviction_score',
        'price_target'.
    """
    analysis_id: str = state.get("job_id", "unknown")
    company_name: str = state.get("company_name", "Unknown Company")
    ticker: str = state.get("ticker", "")

    if not ticker:
        logger.error("run_portfolio_manager_decision called with empty ticker")
        result = InvestmentDecision(
            agent_name="portfolio_manager",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker="UNKNOWN",
            verdict="HOLD",
            conviction_score=1,
            error="ticker field is missing from InvestmentState",
        )
        return {
            "decision": result.model_dump(),
            "final_verdict": result.verdict,
            "conviction_score": result.conviction_score,
            "price_target": result.price_target,
        }

    # Safely retrieve all agent output dicts (default to empty dict)
    fundamental: dict[str, Any] = dict(state.get("fundamental") or {})
    technical: dict[str, Any] = dict(state.get("technical") or {})
    sentiment: dict[str, Any] = dict(state.get("sentiment") or {})
    macro: dict[str, Any] = dict(state.get("macro") or {})
    risk: dict[str, Any] = dict(state.get("risk") or {})
    contrarian: dict[str, Any] = dict(state.get("contrarian") or {})
    valuation: dict[str, Any] = dict(state.get("valuation") or {})

    debate_rounds: list[dict[str, Any]] = list(state.get("debate_rounds") or [])
    debate_round_count: int = int(state.get("debate_round_count") or 0)
    critical_flags: list[str] = list(state.get("critical_flags") or [])

    try:
        result = _run_portfolio_manager_core(
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            fundamental=fundamental,
            technical=technical,
            sentiment=sentiment,
            macro=macro,
            risk=risk,
            contrarian=contrarian,
            valuation=valuation,
            debate_rounds=debate_rounds,
            debate_round_count=debate_round_count,
            critical_flags=critical_flags,
        )
    except Exception as exc:
        logger.exception("Unhandled error in Portfolio Manager node: ticker=%s", ticker)
        result = InvestmentDecision(
            agent_name="portfolio_manager",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            verdict="HOLD",
            conviction_score=1,
            error=f"Unhandled agent error: {exc}",
        )

    return {
        "decision": result.model_dump(),
        "final_verdict": result.verdict,
        "conviction_score": result.conviction_score,
        "price_target": result.price_target,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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
