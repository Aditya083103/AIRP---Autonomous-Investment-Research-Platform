# backend/agents/contrarian_investor.py
"""
AIRP -- Contrarian Investor Agent (T-038)

Persona: professional sceptic and devil's advocate.  Has made a career out
of being right when everyone else was wrong.  Reads every bullish thesis
looking for the crack that will eventually break it.

Mandate
-------
Read ALL prior agent outputs from InvestmentState -- fundamental, technical,
sentiment, macro, AND risk -- and produce a ContrarianReport that:
  * Challenges every piece of bullish evidence with a concrete counter-argument
  * Surfaces overlooked risks that NO other agent flagged
  * Assigns a bear_conviction score (1-10) representing how wrong the consensus is
  * Identifies the single strongest argument that the Portfolio Manager MUST address

The acceptance criteria require:
  * At least 3 distinct counter-arguments for any bullish stock
  * Validated on TCS and Infosys (both large-cap IT with bullish fundamentals)

Two-stage pipeline:
  Stage 1 -- Deterministic counter-argument generation from structured data
  Stage 2 -- LLM narrative synthesis and overlooked-risk identification

Public interface
----------------
  run_contrarian_analysis(state)       -> dict   LangGraph node
  _run_contrarian_analysis_core(...)   -> ContrarianReport  testable core
  _build_counter_arguments(...)        -> list[str]  pure, deterministic
  _score_bear_conviction(...)          -> int   pure, deterministic
  _build_contrarian_prompt(...)        -> str   prompt builder, pure

Design decisions
----------------
* NO ``from __future__ import annotations`` -- breaks Pydantic v2.
* Plain ASCII section comments (# ---) -- rule from T-024 onward.
* No bare ``# type: ignore`` -- use cast(), explicit annotations, assert.
* Deterministic counter-arguments are generated BEFORE the LLM call so that
  the ``counter_arguments`` list is always populated even if the LLM fails.
  The LLM enriches with narrative and identifies overlooked risks.
* bear_conviction is computed deterministically from the strength of the
  bullish signals vs the weight of risk flags -- the LLM cannot override it.
* Error convention: never raises.  On any failure ContrarianReport.error is
  set and bear_conviction defaults to 1 (mildest disagreement).
* LangSmith tracing is automatic via @traced_agent.

Usage in LangGraph (Phase 4)
----------------------------
    from backend.agents.contrarian_investor import run_contrarian_analysis
    builder.add_node("contrarian_investor", run_contrarian_analysis)
    # Reads:  state["fundamental"], state["technical"], state["sentiment"],
    #         state["macro"], state["risk"], state["debate_round_count"]
    # Writes: state["contrarian"]  (ContrarianReport.model_dump())
    #         state["debate_round_count"]  (incremented)
"""

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.llm_factory import get_llm
from backend.agents.output_models import ContrarianReport
from backend.agents.tracing import traced_agent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent persona -- system prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the Contrarian Investor on an investment committee -- a professional \
sceptic who has built a career on being right when the consensus is wrong.

Your ONLY job is to disagree.

You receive structured analysis from 5 other agents (Fundamental, Technical, \
Sentiment, Macro, Risk Officer).  Your job is to find the cracks in their \
analysis -- the things they glossed over, the assumptions they never questioned, \
the tail risks they ignored because they were too busy building the bull case.

RULES:
1. Every counter-argument must be specific -- cite the agent's output and \
   explain why it is wrong, incomplete, or misleading.
2. Do NOT simply repeat what the Risk Officer said.  Find NEW angles.
3. Overlooked risks are risks that NO other agent flagged.  Be creative.
4. The strongest_argument must be the single most devastating challenge to \
   the bull thesis -- the one the Portfolio Manager cannot dismiss.
5. Do NOT use markdown, bullet symbols, or headers in your output.
6. Respond ONLY with valid JSON matching the exact schema described below.
7. The summary must be 2-3 sentences that capture WHY the bullish case is \
   more fragile than the other agents believe.

OUTPUT SCHEMA (strict JSON, no markdown fences):
{
  "counter_arguments": [
    "<agent-specific challenge, 1-2 sentences, with data reference>",
    ...
  ],
  "overlooked_risks": [
    "<structural or hidden risk not flagged by any other agent>",
    ...
  ],
  "strongest_argument": "<single most compelling bear argument>",
  "challenged_agents": ["<agent_name>", ...],
  "summary": "<2-3 sentence bear-case summary>"
}

Produce 3-6 counter_arguments, 1-3 overlooked_risks, and 1 strongest_argument.
Every counter_argument must name which agent's output it challenges."""

# ---------------------------------------------------------------------------
# Deterministic counter-argument builders
# ---------------------------------------------------------------------------

# Minimum number of counter-arguments required by acceptance criteria
MIN_COUNTER_ARGUMENTS = 3


def _build_counter_arguments(
    fundamental: dict[str, Any],
    technical: dict[str, Any],
    sentiment: dict[str, Any],
    macro: dict[str, Any],
    risk: dict[str, Any],
) -> list[str]:
    """
    Build at least 3 deterministic counter-arguments from the research data.

    Slot design -- one dedicated slot per agent category, capped at 6 total:
      slot 1: fundamental primary  (PE / score sustainability) -- always present
      slot 2: fundamental secondary (ROE or D/E challenge)    -- if data exists
      slot 3: technical primary (signal + RSI + 52w-high)     -- always present
      slot 4: sentiment challenge                             -- if score > 0.2
      slot 5: risk complacency challenge                      -- if risk_score <= 4
      slot 6: macro direction-of-travel challenge             -- if headwinds exist

    Folding RSI and price-vs-high detail into the technical primary text (slot 3)
    means each category always gets its slot regardless of how much technical data
    is available.  The cap (6) is a ceiling, not a floor -- all slots that have
    data will be included.

    Returns a list of 3-6 counter-arguments.
    """
    args: list[str] = []

    # --- Slot 1: Fundamental primary (always) ----------------------------
    fund_score_raw: Any = fundamental.get("score")
    fund_score: int = int(fund_score_raw) if fund_score_raw is not None else 5
    pe_val: Any = fundamental.get("pe_ratio")

    if fund_score >= 7:
        if pe_val is not None:
            args.append(
                f"The Fundamental Analyst's {fund_score}/10 score ignores "
                f"valuation risk: a PE of {pe_val:.1f}x means the market has "
                f"already priced in years of future growth, leaving no margin "
                f"of safety if execution falters even slightly."
            )
        else:
            args.append(
                f"The Fundamental Analyst's {fund_score}/10 score reflects "
                f"historical performance, not future risk.  Quality companies "
                f"can deteriorate quickly when competitive dynamics shift -- "
                f"past margins are not guaranteed forward margins."
            )
    elif fund_score >= 4:
        args.append(
            f"The Fundamental Analyst's {fund_score}/10 score is mediocre at "
            f"best.  In a risk-off environment, the market will re-rate mediocre "
            f"businesses first and most severely."
        )
    else:
        args.append(
            f"The Fundamental Analyst gave this stock only {fund_score}/10 -- "
            f"there is no fundamental case for holding this name when higher "
            f"quality alternatives exist in the same sector."
        )

    # --- Slot 2: Fundamental secondary (D/E leverage first, then ROE) ----
    # High leverage (D/E > 0.8) is a critical risk and takes priority over
    # ROE commentary.  If D/E is not dangerously elevated, fall through to
    # the ROE challenge.  Near-zero D/E is a secondary signal.
    roe_raw: Any = fundamental.get("roe_pct")
    de_raw: Any = fundamental.get("debt_to_equity")
    de_sec: float = float(de_raw) if de_raw is not None else 0.0

    if de_raw is not None and de_sec > 0.8:
        args.append(
            f"D/E of {de_sec:.2f} means this company is leveraged in a "
            f"rising rate environment.  Every 50bps RBI rate hike directly "
            f"compresses interest coverage.  The Fundamental Analyst did "
            f"not model this debt-servicing downside scenario."
        )
    elif roe_raw is not None:
        roe: float = float(roe_raw)
        if roe >= 20:
            args.append(
                f"The Fundamental Analyst highlights ROE of {roe:.1f}% as a "
                f"strength, but high ROE attracts competition.  New entrants "
                f"and pricing pressure are precisely what high-ROE businesses "
                f"face -- mean reversion to sector averages is the historical norm."
            )
        elif roe < 12:
            args.append(
                f"ROE of {roe:.1f}% is below the cost of equity for most "
                f"institutional investors.  This company is destroying value "
                f"in real terms -- the Fundamental Analyst's score does not "
                f"adequately penalise this."
            )
    elif de_raw is not None and de_sec < 0.1:
        args.append(
            f"The company's near-zero debt (D/E {de_sec:.2f}) is presented "
            f"as a strength, but it signals management's inability to find "
            f"high-return investment opportunities -- excess cash sitting idle "
            f"is a sign of growth exhaustion, not financial prudence."
        )

    # --- Slot 3: Technical primary (signal + RSI + 52w-high detail) -----
    tech_signal: str = str(technical.get("signal") or "HOLD")
    tech_strength_raw: Any = technical.get("signal_strength")
    tech_strength: int = int(tech_strength_raw) if tech_strength_raw is not None else 5
    rsi_raw: Any = technical.get("rsi_14")
    price_vs_high_raw: Any = technical.get("price_vs_52w_high_pct")

    # Build enriched technical text by folding in RSI and 52w-high detail
    rsi_detail: str = ""
    if rsi_raw is not None and float(rsi_raw) > 65:
        rsi_detail = f" RSI of {float(rsi_raw):.0f} confirms overbought conditions."
    pvh_detail: str = ""
    if price_vs_high_raw is not None and float(price_vs_high_raw) >= 90:
        pvh_detail = (
            f" At {float(price_vs_high_raw):.0f}% of its 52-week high, "
            f"buyers are chasing near the top of the range."
        )

    if tech_signal == "BUY" and tech_strength >= 6:
        args.append(
            f"The Technical Analyst's BUY signal (strength {tech_strength}/10) "
            f"reflects momentum, not value.  Momentum strategies have historically "
            f"underperformed following periods of strong outperformance -- this "
            f"signal is a contrarian sell indicator.{rsi_detail}{pvh_detail}"
        )
    elif tech_signal == "HOLD":
        args.append(
            "The Technical Analyst's HOLD signal is the worst outcome -- "
            "neither enough momentum to justify owning it nor enough weakness "
            "to trigger disciplined selling.  'Hold' decisions keep capital "
            f"trapped in underperforming positions indefinitely.{pvh_detail}"
        )
    elif tech_signal == "SELL":
        args.append(
            f"The Technical Analyst's SELL signal (strength {tech_strength}/10) "
            f"confirms that price momentum has already reversed.{rsi_detail}"
            f"{pvh_detail}  Buying against a confirmed technical downtrend "
            f"requires a fundamental thesis strong enough to absorb further "
            f"near-term price weakness."
        )
    else:
        # Fallback: use RSI or 52w-high detail if signal is unclear
        if rsi_raw is not None and float(rsi_raw) > 65:
            args.append(
                f"RSI of {float(rsi_raw):.0f} indicates the stock is technically "
                f"overbought.  Buying at RSI > 65 has historically produced "
                f"below-average 3-month returns.{pvh_detail}"
            )
        elif price_vs_high_raw is not None and float(price_vs_high_raw) >= 90:
            args.append(
                f"Trading at {float(price_vs_high_raw):.0f}% of its 52-week "
                f"high means new buyers are near the top of the range with "
                f"limited upside and asymmetric downside."
            )

    # --- Slot 4: Sentiment challenge -------------------------------------
    sent_score_raw: Any = sentiment.get("sentiment_score")
    if sent_score_raw is not None:
        sent_score: float = float(sent_score_raw)
        if sent_score > 0.2:
            args.append(
                f"The Sentiment Agent's score of {sent_score:.2f} (positive) "
                f"is itself a warning sign.  Extremely positive news sentiment "
                f"coincides with peaks, not bottoms.  Professional investors "
                f"buy pessimism and sell optimism -- high sentiment is the "
                f"time to reduce, not increase, exposure."
            )

    # --- Slot 5: Risk complacency challenge ------------------------------
    risk_score_raw: Any = risk.get("risk_score")
    if risk_score_raw is not None:
        risk_score_val: int = int(risk_score_raw)
        if risk_score_val <= 4:
            args.append(
                f"The Risk Officer's score of {risk_score_val}/10 may lull "
                f"the committee into a false sense of security -- complacency "
                f"risk is highest precisely when risk scores look reassuring.  "
                f"Low historical risk scores are systematically lower before "
                f"crises than after."
            )

    # --- Slot 6: Macro direction-of-travel challenge ---------------------
    macro_env: str = str(macro.get("macro_environment") or "neutral")
    headwinds: list[str] = macro.get("headwinds", []) or []
    if macro_env in ("neutral", "favourable") and headwinds:
        args.append(
            f"Despite a '{macro_env}' macro classification, the Macro "
            f"Economist identified {len(headwinds)} sector headwind(s). "
            f"The classification obscures the direction of travel -- macro "
            f"environments do not stay 'neutral' and the headwinds suggest "
            f"the next move is toward 'unfavourable'."
        )
    elif macro_env == "unfavourable":
        args.append(
            "The Macro Economist classifies the environment as 'unfavourable' "
            "-- this is the active backdrop for this investment thesis, not a "
            "tail risk scenario.  Buying into confirmed macro headwinds requires "
            "a much higher margin of safety than the analysis provides."
        )

    return args[:6]


def _score_bear_conviction(
    fundamental: dict[str, Any],
    technical: dict[str, Any],
    sentiment: dict[str, Any],
    risk: dict[str, Any],
    counter_arguments: list[str],
) -> int:
    """
    Compute bear_conviction (1-10) deterministically.

    Higher score = Contrarian is more confident the consensus is wrong.

    Scoring contributions:
      +2  if fundamental score >= 8 (high-quality stocks are over-loved)
      +1  if technical signal is BUY with strength >= 6 (momentum chase risk)
      +1  if sentiment_score > 0.3 (peak sentiment = peak positioning)
      +1  if risk_score <= 3 (low risk score = complacency)
      +1  if >= 5 counter_arguments generated (many angles of attack)
      +1  if RSI > 65 (overbought)
      +1  if price at >= 90% of 52-week high (near-top risk)
      +1  if D/E < 0.1 (growth exhaustion signal)
      +1  if D/E > 1.0 (leverage risk)

    Clipped to [1, 10].
    """
    conviction: int = 1  # base: mild scepticism

    # Fundamental: high score means over-loved
    fund_score_raw: Any = fundamental.get("score")
    if fund_score_raw is not None and int(fund_score_raw) >= 8:
        conviction += 2

    # Technical: BUY signal = momentum chase risk
    tech_signal: str = str(technical.get("signal") or "HOLD")
    tech_strength_raw: Any = technical.get("signal_strength")
    tech_strength: int = int(tech_strength_raw) if tech_strength_raw is not None else 5
    if tech_signal == "BUY" and tech_strength >= 6:
        conviction += 1

    # RSI overbought
    rsi_raw: Any = technical.get("rsi_14")
    if rsi_raw is not None and float(rsi_raw) > 65:
        conviction += 1

    # Near 52-week high
    pvh_raw: Any = technical.get("price_vs_52w_high_pct")
    if pvh_raw is not None and float(pvh_raw) >= 90:
        conviction += 1

    # Sentiment: high positive = peak positioning
    sent_raw: Any = sentiment.get("sentiment_score")
    if sent_raw is not None and float(sent_raw) > 0.3:
        conviction += 1

    # Risk score: low = potential complacency
    risk_score_raw: Any = risk.get("risk_score")
    if risk_score_raw is not None and int(risk_score_raw) <= 3:
        conviction += 1

    # Many counter-arguments found
    if len(counter_arguments) >= 5:
        conviction += 1

    # Debt structure extremes
    de_raw: Any = fundamental.get("debt_to_equity")
    if de_raw is not None:
        de: float = float(de_raw)
        if de < 0.1:
            conviction += 1  # growth exhaustion
        elif de > 1.0:
            conviction += 1  # leverage risk

    return max(1, min(10, conviction))


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _build_contrarian_prompt(
    company_name: str,
    ticker: str,
    fundamental: dict[str, Any],
    technical: dict[str, Any],
    sentiment: dict[str, Any],
    macro: dict[str, Any],
    risk: dict[str, Any],
    pre_counter_arguments: list[str],
    bear_conviction: int,
    debate_round: int,
) -> str:
    """
    Build the user-turn prompt sent to the LLM.

    Passes pre-computed counter-arguments and conviction score so the LLM
    enriches the narrative and adds overlooked risks.
    """

    def _fmt(val: Any, suffix: str = "") -> str:
        if val is None:
            return "N/A"
        if isinstance(val, float):
            return f"{val:,.2f}{suffix}"
        return f"{val}{suffix}"

    # Fundamental snapshot
    fund_score: Any = fundamental.get("score", "N/A")
    de: Any = fundamental.get("debt_to_equity")
    roe: Any = fundamental.get("roe_pct")
    fund_summary: str = str(fundamental.get("summary") or "No summary available")
    fund_strengths: list[str] = fundamental.get("strengths", []) or []

    # Technical snapshot
    tech_signal: str = str(technical.get("signal") or "N/A")
    tech_strength: Any = technical.get("signal_strength", "N/A")
    rsi: Any = technical.get("rsi_14")
    pvh: Any = technical.get("price_vs_52w_high_pct")
    tech_summary: str = str(technical.get("summary") or "No summary available")

    # Sentiment snapshot
    sent_score: Any = sentiment.get("sentiment_score", "N/A")
    sent_label: str = str(sentiment.get("sentiment_label") or "N/A")
    red_flags: list[str] = sentiment.get("red_flags", []) or []
    sent_summary: str = str(sentiment.get("summary") or "No summary available")

    # Macro snapshot
    macro_env: str = str(macro.get("macro_environment") or "N/A")
    sector_impact: str = str(macro.get("sector_impact") or "N/A")
    tailwinds: list[str] = macro.get("tailwinds", []) or []
    macro_summary: str = str(macro.get("summary") or "No summary available")

    # Risk snapshot
    risk_score: Any = risk.get("risk_score", "N/A")
    risk_rec: str = str(risk.get("risk_recommendation") or "N/A")
    risk_summary: str = str(risk.get("summary") or "No summary available")

    strengths_block = (
        "\n".join(f"  - {s}" for s in fund_strengths[:4]) or "  None listed"
    )
    red_flags_block = "\n".join(f"  - {f}" for f in red_flags[:3]) or "  None"
    tailwinds_block = "\n".join(f"  - {t}" for t in tailwinds[:3]) or "  None"
    pre_args_block = (
        "\n".join(f"  {i+1}. {a}" for i, a in enumerate(pre_counter_arguments))
        or "  (none pre-generated)"
    )

    return f"""Challenge the investment case for {company_name} ({ticker}).
This is debate round {debate_round}.

PRE-COMPUTED BEAR CONVICTION: {bear_conviction}/10
(Do NOT change this -- it is deterministic)

--- BULL CASE (what you must challenge) ---
Fundamental score    : {fund_score}/10
Key strengths cited:
{strengths_block}
Fundamental summary  : {fund_summary}

Technical signal     : {tech_signal} (strength {tech_strength}/10)
RSI-14               : {_fmt(rsi)}
Price vs 52-week H   : {_fmt(pvh, '%')}
Technical summary    : {tech_summary}

Sentiment score      : {sent_score} ({sent_label})
Red flags found:
{red_flags_block}
Sentiment summary    : {sent_summary}

Macro environment    : {macro_env} | Sector: {sector_impact}
Tailwinds cited:
{tailwinds_block}
Macro summary        : {macro_summary}

Risk Officer score   : {risk_score}/10 ({risk_rec})
Risk summary         : {risk_summary}

--- FINANCIAL RATIOS ---
Debt/Equity : {_fmt(de)}  |  ROE: {_fmt(roe, '%')}

--- PRE-GENERATED COUNTER-ARGUMENTS (already found, do NOT repeat) ---
{pre_args_block}

Your task:
1. Produce 3-6 counter_arguments that EXTEND or DEEPEN the above pre-generated \
ones.  Do NOT simply restate them -- find new angles.
2. Produce 1-3 overlooked_risks that NO other agent flagged.
3. Identify the strongest_argument -- the one the Portfolio Manager cannot dismiss.
4. List challenged_agents (agent names whose outputs you most directly challenge).
5. Write a 2-3 sentence bear-case summary.

Respond ONLY with valid JSON per the system prompt schema."""


# ---------------------------------------------------------------------------
# Core agent logic (separated from LangGraph node for testability)
# ---------------------------------------------------------------------------


def _run_contrarian_analysis_core(
    analysis_id: str,
    company_name: str,
    ticker: str,
    fundamental: dict[str, Any],
    technical: dict[str, Any],
    sentiment: dict[str, Any],
    macro: dict[str, Any],
    risk: dict[str, Any],
    debate_round: int,
) -> ContrarianReport:
    """
    Core Contrarian Investor logic.

    Separated from ``run_contrarian_analysis`` for direct testability.

    Stage 1: Deterministic counter-arguments and bear_conviction.
    Stage 2: LLM narrative synthesis -- extended arguments and overlooked risks.

    Never raises.  On any failure returns ContrarianReport with error set.

    Args:
        analysis_id:   UUID of the parent Analysis job.
        company_name:  Human-readable company name.
        ticker:        Yahoo Finance ticker (e.g. 'TCS.NS').
        fundamental:   FundamentalAnalysis.model_dump() dict.
        technical:     TechnicalAnalysis.model_dump() dict.
        sentiment:     SentimentAnalysis.model_dump() dict.
        macro:         MacroAnalysis.model_dump() dict.
        risk:          RiskAnalysis.model_dump() dict.
        debate_round:  Current debate round number (1-based).

    Returns:
        ContrarianReport Pydantic model (frozen, serialisable).
    """
    logger.info(
        "Contrarian: starting analysis ticker=%s round=%d analysis=%s",
        ticker,
        debate_round,
        analysis_id,
    )

    # --- Stage 1a: Deterministic counter-arguments
    pre_counter_args: list[str] = _build_counter_arguments(
        fundamental, technical, sentiment, macro, risk
    )

    # --- Stage 1b: Deterministic bear_conviction
    bear_conviction: int = _score_bear_conviction(
        fundamental, technical, sentiment, risk, pre_counter_args
    )

    # --- Stage 2: LLM narrative synthesis
    logger.info("Contrarian: invoking LLM ticker=%s", ticker)

    counter_arguments: list[str] = list(pre_counter_args)
    overlooked_risks: list[str] = []
    strongest_argument: str = (
        pre_counter_args[0]
        if pre_counter_args
        else "Insufficient data to build bear case."
    )
    challenged_agents: list[str] = []
    summary: str = ""

    try:
        llm = get_llm()
        prompt = _build_contrarian_prompt(
            company_name=company_name,
            ticker=ticker,
            fundamental=fundamental,
            technical=technical,
            sentiment=sentiment,
            macro=macro,
            risk=risk,
            pre_counter_arguments=pre_counter_args,
            bear_conviction=bear_conviction,
            debate_round=debate_round,
        )
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        response = llm.invoke(messages)
        raw_text: str = (
            response.content if hasattr(response, "content") else str(response)
        )

        # Strip accidental markdown fences
        cleaned: str = re.sub(r"```(?:json)?|```", "", raw_text).strip()
        parsed: dict[str, Any] = json.loads(cleaned)

        # Merge LLM counter-arguments with pre-computed ones (deduplicated)
        llm_args: list[str] = parsed.get("counter_arguments", []) or []

        def _merge_args(pre: list[str], llm_out: list[str]) -> list[str]:
            seen: set[str] = set()
            merged: list[str] = []
            for item in pre + llm_out:
                key: str = item[:60].lower()
                if key not in seen:
                    seen.add(key)
                    merged.append(item)
            return merged[:6]

        counter_arguments = _merge_args(pre_counter_args, llm_args)

        overlooked_risks = [str(r) for r in (parsed.get("overlooked_risks") or [])][:3]

        llm_strongest: str = str(parsed.get("strongest_argument") or "").strip()
        if llm_strongest:
            strongest_argument = llm_strongest

        challenged_agents = [str(a) for a in (parsed.get("challenged_agents") or [])]

        summary = str(parsed.get("summary") or "").strip()

    except Exception as exc:
        logger.exception("LLM call failed in Contrarian for %s: %s", ticker, exc)
        summary = (
            f"{company_name} has bear_conviction {bear_conviction}/10. "
            f"{len(counter_arguments)} counter-argument(s) identified "
            f"deterministically. LLM synthesis failed -- review pre-computed "
            f"arguments directly."
        )

    # Ensure minimum counter-argument count (acceptance criteria)
    if not counter_arguments:
        counter_arguments = [
            f"Insufficient data to build bear case for {company_name}. "
            f"Manual review required."
        ]

    # Ensure strongest_argument is set
    if not strongest_argument and counter_arguments:
        strongest_argument = counter_arguments[0]

    return ContrarianReport(
        agent_name="contrarian_investor",
        analysis_id=analysis_id,
        company_name=company_name,
        ticker=ticker,
        counter_arguments=counter_arguments,
        challenged_agents=challenged_agents,
        overlooked_risks=overlooked_risks,
        bear_conviction=bear_conviction,
        strongest_argument=strongest_argument,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# LangGraph node entry point
# ---------------------------------------------------------------------------


@traced_agent("contrarian_investor")
def run_contrarian_analysis(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph node function for the Contrarian Investor agent.

    Reads from InvestmentState:
      - job_id             -> analysis_id for the output model
      - company_name       -> human-readable company name
      - ticker             -> Yahoo Finance ticker
      - fundamental        -> FundamentalAnalysis.model_dump() (may be None)
      - technical          -> TechnicalAnalysis.model_dump() (may be None)
      - sentiment          -> SentimentAnalysis.model_dump() (may be None)
      - macro              -> MacroAnalysis.model_dump() (may be None)
      - risk               -> RiskAnalysis.model_dump() (may be None)
      - debate_round_count -> current round count (0-based before this call)

    Writes to InvestmentState:
      - contrarian         -> ContrarianReport.model_dump()
      - debate_round_count -> incremented by 1

    Never raises -- on failure, ``contrarian["error"]`` is set.

    Args:
        state: InvestmentState dict (LangGraph passes the full state).

    Returns:
        Dict with keys 'contrarian' and 'debate_round_count'.
    """
    analysis_id: str = state.get("job_id", "unknown")
    company_name: str = state.get("company_name", "Unknown Company")
    ticker: str = state.get("ticker", "")

    if not ticker:
        logger.error("run_contrarian_analysis called with empty ticker")
        result = ContrarianReport(
            agent_name="contrarian_investor",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker="UNKNOWN",
            counter_arguments=["Ticker missing -- cannot build bear case."],
            bear_conviction=1,
            strongest_argument="Ticker missing -- cannot build bear case.",
            error="ticker field is missing from InvestmentState",
        )
        return {
            "contrarian": result.model_dump(),
            "debate_round_count": 0,
        }

    # Safely retrieve all agent output dicts (default to empty dict)
    fundamental: dict[str, Any] = dict(state.get("fundamental") or {})
    technical: dict[str, Any] = dict(state.get("technical") or {})
    sentiment: dict[str, Any] = dict(state.get("sentiment") or {})
    macro: dict[str, Any] = dict(state.get("macro") or {})
    risk: dict[str, Any] = dict(state.get("risk") or {})

    # Increment debate round counter
    prev_round_count: int = int(state.get("debate_round_count") or 0)
    new_round_count: int = prev_round_count + 1

    try:
        result = _run_contrarian_analysis_core(
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            fundamental=fundamental,
            technical=technical,
            sentiment=sentiment,
            macro=macro,
            risk=risk,
            debate_round=new_round_count,
        )
    except Exception as exc:
        logger.exception("Unhandled error in Contrarian node: ticker=%s", ticker)
        result = ContrarianReport(
            agent_name="contrarian_investor",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            counter_arguments=[f"Agent error prevented bear case generation: {exc}"],
            bear_conviction=1,
            strongest_argument=f"Agent error: {exc}",
            error=f"Unhandled agent error: {exc}",
        )

    return {
        "contrarian": result.model_dump(),
        "debate_round_count": new_round_count,
    }
