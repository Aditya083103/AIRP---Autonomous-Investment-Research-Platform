# backend/agents/risk_officer.py
"""
AIRP -- Risk Officer Agent (T-037)

Persona: paranoid risk manager who has seen every corporate scandal in the
Indian equity market since Harshad Mehta.  Reads every research agent's
output with deep scepticism, looking for what the optimists missed.

Mandate
-------
Read all 4 research agent outputs from InvestmentState and produce a
structured RiskAnalysis with:
  * risk_score 1-10 (composite: higher = riskier)
  * governance_risk, regulatory_risk, financial_risk, concentration_risk
    (each 1-10)
  * governance_flags[]  -- named governance / management quality concerns
  * regulatory_risks[]  -- active or latent regulatory / legal exposures
  * fraud_indicators[]  -- accounting or conduct red flags
  * concentration_risks[] -- customer/geo/revenue dependency flags
  * critical_flags[]    -- subset that are severe enough to be memo-blocking
  * risk_recommendation -- 'proceed_with_caution' | 'monitor_closely' | 'avoid'
  * summary             -- 2-3 sentences, PM-ready

Two-stage pipeline (same pattern as all AIRP agents):
  Stage 1 -- Deterministic risk scoring from structured research outputs
  Stage 2 -- LLM narrative synthesis of governance/fraud flags

Public interface
----------------
  run_risk_analysis(state)          -> dict   LangGraph node
  _run_risk_analysis_core(...)      -> RiskAnalysis  testable core
  _score_risk(...)                  -> dict   pure deterministic scorer
  _extract_sentinel_flags(...)      -> dict   pure flag extractor
  _build_risk_prompt(...)           -> str    prompt builder, pure

Design decisions
----------------
* NO ``from __future__ import annotations`` -- breaks Pydantic v2.
* Plain ASCII section comments (# ---) -- rule from T-024 onward.
* No bare ``# type: ignore`` -- use cast(), explicit annotations, assert.
* The deterministic scorer reads sentiment red_flags, fundamental scores,
  technical signals, and macro headwinds to produce sub-scores.  The LLM
  ONLY synthesises narrative for governance/fraud flags -- it cannot change
  the numeric scores.
* Sentinel keyword detection (fraud, SEBI, pledge, restatement ...) runs
  on all text fields from research outputs BEFORE the LLM call, so the
  critical_flags list is always populated regardless of LLM availability.
* Error convention: never raises.  On any failure, RiskAnalysis.error is set
  and risk_score defaults to 5 (unknown/neutral).
* LangSmith tracing is automatic via @traced_agent.

Usage in LangGraph (Phase 4)
----------------------------
    from backend.agents.risk_officer import run_risk_analysis
    builder.add_node("risk_officer", run_risk_analysis)
    # Reads:  state["job_id"], state["company_name"], state["ticker"],
    #         state["fundamental"], state["technical"], state["sentiment"],
    #         state["macro"]
    # Writes: state["risk"] (RiskAnalysis.model_dump()),
    #         state["risk_flags"], state["critical_flags"]
"""

import json
import logging
import re
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.llm_factory import get_llm
from backend.agents.output_models import RiskAnalysis
from backend.agents.tracing import traced_agent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent persona -- system prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the Risk Officer of an investment committee -- a paranoid, \
battle-hardened risk manager who has seen every corporate scandal in \
the Indian equity market.  You have lived through Satyam, IL&FS, DHFL, \
Yes Bank, and Zee Entertainment.  You trust nothing.

Your sole mandate: find what the optimists missed.

You receive structured research from 4 specialist agents (Fundamental, \
Technical, Sentiment, Macro).  Your job is to identify governance failures, \
fraud indicators, regulatory exposures, and concentration risks that those \
agents may have glossed over.

RULES:
1. Be specific -- cite actual data points from the research provided.
2. Every flag must name the specific risk, not a generic category.
3. If the Sentiment agent found red flags, you MUST investigate further.
4. If D/E is high or rising, flag it with the actual ratio.
5. Never say "looks clean" unless the data explicitly supports it.
6. The summary must be 2-3 sentences maximum, written for a Portfolio Manager \
   who will decide whether to proceed, monitor, or avoid this investment.
7. Do NOT use markdown, bullet symbols, or headers in your output.
8. Respond ONLY with valid JSON matching the exact schema described below.

OUTPUT SCHEMA (strict JSON, no markdown fences):
{
  "governance_flags": ["<specific governance concern with evidence>", ...],
  "regulatory_risks": ["<specific regulatory or legal exposure>", ...],
  "fraud_indicators": ["<specific accounting or conduct red flag>", ...],
  "concentration_risks": ["<specific concentration dependency>", ...],
  "risk_recommendation": "proceed_with_caution" | "monitor_closely" | "avoid",
  "summary": "<2-3 sentence PM-ready risk summary>"
}

Produce 0-5 items per list (empty list when genuinely clean on that dimension).
Every non-empty item must reference a specific metric, event, or data point \
from the research provided."""

# ---------------------------------------------------------------------------
# Sentinel keyword sets for deterministic flag detection
# ---------------------------------------------------------------------------

# Keywords that -- when found in any research text field -- indicate potential
# fraud or governance failure.  Detection is case-insensitive.
_FRAUD_KEYWORDS: list[str] = [
    "fraud",
    "scam",
    "embezzlement",
    "misappropriation",
    "restatement",
    "whistleblower",
    "forgery",
    "falsification",
    "ponzi",
    "round-tripping",
    "money laundering",
    "insider trading",
    "front-running",
    "manipulation",
    "kickback",
]

# Keywords indicating regulatory exposure
# T-095 audit fix: bare "sebi", "notice", "fine", and "ban" were removed --
# "sebi" alone is just the regulator's name (fires on routine, entirely
# neutral disclosure text like "as per SEBI regulations"); "notice" is
# ordinary English ("investors should take notice of strong growth");
# "fine" is an ambiguous adjective ("a fine quarter"); and, because the
# matching below used plain substring containment (fixed in this same
# patch -- see _contains_keyword), bare "ban" matched inside "Bangalore"
# and "banking". Each is replaced with the specific multi-word phrase
# that actually carries the regulatory-risk meaning; "nclt petition" and
# "gst notice" already were multi-word and are unaffected.
# T-095 follow-up: the six "sebi <action>" phrases previously here were
# exact-adjacent literals ("sebi probe", "sebi notice", ...) -- too rigid
# for real research text ("SEBI has issued a notice to the company" isn't
# caught by the literal substring "sebi notice"). Replaced with the
# _sebi_action_present() proximity check in _extract_sentinel_flags below.
_REGULATORY_KEYWORDS: list[str] = [
    "investigation",
    "probe",
    "regulatory notice",
    "show cause notice",
    "monetary penalty",
    "trading ban",
    "market ban",
    "debarment",
    "enforcement action",
    "nclt petition",
    "cci probe",
    "rbi directive",
    "ed raid",
    "cbi",
    "it department raid",
    "gst notice",
    "contempt",
    "arrest",
]

# Keywords indicating governance / management quality problems
#
# T-095 audit fix: "related party" and "minority shareholders" are
# standard, routine disclosure terminology -- every annual report has a
# "related party transactions" section and discusses minority
# shareholder protections, regardless of whether anything is wrong.
# "preferential allotment" is a normal, often perfectly healthy capital-
# raising mechanism, not inherently a governance concern. Bare "pledged"
# is replaced with the specific "shares pledged" / "stock pledged" so it
# doesn't fire on unrelated uses of "pledged" (e.g. "pledged support for
# the merger"). Each is now scoped to the phrase that actually signals a
# problem.
# T-095 follow-up: "ceo resign" / "cfo resign" / "director resign" were
# exact-adjacent literals, too rigid for real phrasing ("the CFO is
# expected to resign next quarter"). Replaced with the
# _resignation_present() proximity check in _extract_sentinel_flags below.
_GOVERNANCE_KEYWORDS: list[str] = [
    "promoter pledge",
    "shares pledged",
    "stock pledged",
    "related party concerns",
    "related party dispute",
    "tunnelling",
    "minority shareholder rights violation",
    "oppression of minority shareholders",
    "audit qualification",
    "auditor change",
    "auditor resignation",
    "board reconstitution",
    "rights issue dilution",
]

# ---------------------------------------------------------------------------
# Pure helpers: deterministic scoring
# ---------------------------------------------------------------------------

_WORD_BOUNDARY_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


def _contains_keyword(keyword: str, text: str) -> bool:
    """
    True if ``keyword`` occurs in ``text`` as a whole word/phrase, not
    merely as a substring of a longer, unrelated word.

    T-095 audit fix: every keyword scan in this module previously used
    plain Python `in` containment, e.g. `if kw in all_text`. That matches
    "ban" inside "Bangalore" or "banking" -- a false positive that
    previously counted as a real regulatory-risk signal. A regex
    `\\b...\\b` word boundary still matches multi-word phrases (e.g.
    "sebi probe") as a unit, since the boundary anchors on the phrase's
    own first/last characters.
    """
    pattern = _WORD_BOUNDARY_PATTERN_CACHE.get(keyword)
    if pattern is None:
        pattern = re.compile(r"\b" + re.escape(keyword) + r"\b")
        _WORD_BOUNDARY_PATTERN_CACHE[keyword] = pattern
    return pattern.search(text) is not None


# ---------------------------------------------------------------------------
# Proximity matching (T-095 follow-up)
# ---------------------------------------------------------------------------
#
# Exact adjacent multi-word phrases (e.g. "sebi notice") are too rigid for
# real research text, which rarely places the two words directly next to
# each other ("SEBI has issued a notice", "the CFO is expected to resign").
# A proximity match -- an anchor word (e.g. "sebi") within a small window
# of a trigger word (e.g. "notice"), both whole words -- keeps the
# original word-boundary fix's guarantee (a bare anchor with no nearby
# trigger still never fires) while catching natural phrasing of a genuine
# event.
_TOKEN_PATTERN: re.Pattern[str] = re.compile(r"\w+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text.lower())


def _anchor_near_trigger(
    anchors: frozenset[str], triggers: frozenset[str], text: str, window: int
) -> bool:
    """True if any ``anchors`` word is within ``window`` words of any
    ``triggers`` word in ``text`` (whole-word matches only)."""
    tokens = _tokenize(text)
    anchor_idxs = [i for i, t in enumerate(tokens) if t in anchors]
    if not anchor_idxs:
        return False
    trigger_idxs = [i for i, t in enumerate(tokens) if t in triggers]
    if not trigger_idxs:
        return False
    return any(abs(a - t) <= window for a in anchor_idxs for t in trigger_idxs)


_SEBI_ANCHORS: frozenset[str] = frozenset({"sebi"})
_SEBI_TRIGGERS: frozenset[str] = frozenset(
    {
        "probe",
        "notice",
        "penalty",
        "fine",
        "fined",
        "ban",
        "banned",
        "action",
        "order",
        "investigating",
        "investigation",
        "debar",
        "debarred",
    }
)
_SEBI_PROXIMITY_WINDOW = 8

_RESIGNATION_ANCHORS: frozenset[str] = frozenset(
    {"ceo", "md", "cfo", "director", "chairman", "chairperson"}
)
_RESIGNATION_TRIGGERS: frozenset[str] = frozenset(
    {"resign", "resigns", "resigned", "resignation", "quit", "quits", "quitting"}
)
_RESIGNATION_PROXIMITY_WINDOW = 4


def _sebi_action_present(text: str) -> bool:
    """True if 'sebi' appears near a regulatory-action trigger word."""
    return _anchor_near_trigger(
        _SEBI_ANCHORS, _SEBI_TRIGGERS, text, _SEBI_PROXIMITY_WINDOW
    )


def _resignation_present(text: str) -> bool:
    """True if a leadership role appears near a resignation trigger word."""
    return _anchor_near_trigger(
        _RESIGNATION_ANCHORS,
        _RESIGNATION_TRIGGERS,
        text,
        _RESIGNATION_PROXIMITY_WINDOW,
    )


def _collect_all_text(
    fundamental: dict[str, Any],
    technical: dict[str, Any],
    sentiment: dict[str, Any],
    macro: dict[str, Any],
) -> str:
    """
    Flatten all string fields from all 4 research dicts into a single
    lowercase string for keyword scanning.

    This approach is intentionally broad -- we want to catch any mention
    of risk keywords regardless of which field they appear in.
    """
    pieces: list[str] = []
    for d in (fundamental, technical, sentiment, macro):
        if not d:
            continue
        for val in d.values():
            if isinstance(val, str):
                pieces.append(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        pieces.append(item)
    return " ".join(pieces).lower()


def _extract_sentinel_flags(
    all_text: str,
    sentiment: dict[str, Any],
) -> dict[str, list[str]]:
    """
    Run keyword-based detection on the combined research text to surface
    fraud indicators, regulatory exposures, and governance concerns.

    Returns a dict with three keys:
      fraud_indicators  -- list of matched fraud-related sentences
      regulatory_risks  -- list of matched regulatory-related sentences
      governance_flags  -- list of matched governance-related sentences

    Detection strategy:
      1. Check sentiment red_flags (already extracted by Sentiment agent)
      2. Scan all_text for sentinel keywords
      3. Each match produces a 1-sentence descriptive flag

    This function is pure (no I/O, no LLM) and fully unit-testable.
    """
    fraud_indicators: list[str] = []
    regulatory_risks: list[str] = []
    governance_flags: list[str] = []

    # Step 1: Inherit Sentiment agent's red_flags directly
    sentiment_red_flags: list[str] = sentiment.get("red_flags", []) or []
    for flag in sentiment_red_flags:
        flag_lower = flag.lower()
        if any(_contains_keyword(kw, flag_lower) for kw in _FRAUD_KEYWORDS):
            fraud_indicators.append(f"News sentiment red flag: {flag}")
        elif any(
            _contains_keyword(kw, flag_lower) for kw in _REGULATORY_KEYWORDS
        ) or _sebi_action_present(flag_lower):
            regulatory_risks.append(f"News sentiment red flag: {flag}")
        elif any(
            _contains_keyword(kw, flag_lower) for kw in _GOVERNANCE_KEYWORDS
        ) or _resignation_present(flag_lower):
            governance_flags.append(f"News sentiment red flag: {flag}")
        else:
            # Generic red flag -- classify as governance by default
            governance_flags.append(f"News sentiment red flag: {flag}")

    # Step 2: Keyword scan on full research text
    for kw in _FRAUD_KEYWORDS:
        if _contains_keyword(kw, all_text) and not any(
            _contains_keyword(kw, f.lower()) for f in fraud_indicators
        ):
            fraud_indicators.append(
                f"Keyword '{kw}' detected in research text -- manual review required"
            )

    for kw in _REGULATORY_KEYWORDS:
        if _contains_keyword(kw, all_text) and not any(
            _contains_keyword(kw, r.lower()) for r in regulatory_risks
        ):
            regulatory_risks.append(
                f"Keyword '{kw}' detected in research text -- "
                "potential regulatory exposure"
            )

    if _sebi_action_present(all_text) and not any(
        _contains_keyword("sebi", r.lower()) for r in regulatory_risks
    ):
        regulatory_risks.append(
            "Keyword 'sebi action' detected in research text -- "
            "potential regulatory exposure"
        )

    for kw in _GOVERNANCE_KEYWORDS:
        if _contains_keyword(kw, all_text) and not any(
            _contains_keyword(kw, g.lower()) for g in governance_flags
        ):
            governance_flags.append(
                f"Keyword '{kw}' detected in research text -- "
                "governance concern flagged"
            )

    if _resignation_present(all_text) and not any(
        _contains_keyword("resign", g.lower()) for g in governance_flags
    ):
        governance_flags.append(
            "Keyword 'executive resignation' detected in research text -- "
            "governance concern flagged"
        )

    return {
        "fraud_indicators": fraud_indicators[:5],  # cap at 5 per category
        "regulatory_risks": regulatory_risks[:5],
        "governance_flags": governance_flags[:5],
    }


def _score_risk(
    fundamental: dict[str, Any],
    technical: dict[str, Any],
    sentiment: dict[str, Any],
    macro: dict[str, Any],
    sentinel_flags: dict[str, list[str]],
) -> dict[str, Any]:
    """
    Compute four sub-scores (each 1-10, higher = riskier) and a composite.

    Sub-scores
    ----------
    governance_risk:
      Driven by sentiment red_flags and governance sentinel keywords.
      Base 2; +2 per red flag (cap 8); +2 if governance keywords detected.

    regulatory_risk:
      Driven by regulatory sentinel keywords and sentiment score.
      Base 2; +2 per regulatory keyword match (cap 8).

    financial_risk:
      Driven by fundamental agent data: D/E ratio, FCF status, margin trends.
      Base 3; +3 if D/E > 1.0; +2 if D/E 0.5-1.0; +2 if FCF negative or
      weak; +1 if fundamental score <= 4. Skipped entirely -- stays at the
      neutral base of 3 -- when fundamental.data_quality == "insufficient"
      (T-082): an absent fundamental score must never be treated as a risk
      signal, and partial fragments (e.g. a lone D/E figure) are not a
      reliable basis for a risk adjustment either.

    concentration_risk:
      Qualitative -- base 3, elevated if macro headwinds >= 3 or if
      technical signal is SELL with low signal_strength.

    composite risk_score:
      Weighted average rounded to [1, 10]:
        governance_risk   x 0.30
        regulatory_risk   x 0.25
        financial_risk    x 0.30
        concentration_risk x 0.15

    Returns a dict with keys:
      governance_risk, regulatory_risk, financial_risk,
      concentration_risk, risk_score
    """
    # --- Governance risk
    red_flag_count: int = int(sentiment.get("red_flag_count") or 0)
    gov_flags: list[str] = sentinel_flags.get("governance_flags", [])
    governance_risk: int = min(10, 2 + red_flag_count * 2 + (2 if gov_flags else 0))

    # --- Regulatory risk
    reg_risks: list[str] = sentinel_flags.get("regulatory_risks", [])
    regulatory_risk: int = min(10, 2 + len(reg_risks) * 2)

    # --- Financial risk (from fundamental agent)
    financial_risk: int = 3  # default: moderate

    fund_data_quality: str = str(fundamental.get("data_quality") or "sufficient")

    if fund_data_quality == "insufficient":
        # T-082: fewer than 2 of the fundamental analyst's 5 scoring metrics
        # were available. An absence of data is not itself evidence of
        # financial weakness -- stay at the neutral base rather than let
        # whichever fragments happen to be present (e.g. a lone D/E value)
        # silently swing the risk score.
        logger.info(
            "Fundamental data_quality=insufficient -- financial_risk held "
            "at neutral base (3), skipping D/E and FCF adjustments"
        )
    else:
        de_raw: Any = fundamental.get("debt_to_equity")
        de: Optional[float] = float(de_raw) if de_raw is not None else None

        if de is not None:
            if de > 1.0:
                financial_risk += 3
            elif de > 0.5:
                financial_risk += 2
            elif de < 0:
                # Negative D/E = net cash = lower financial risk
                financial_risk -= 1

        # FCF status from weaknesses or summary text
        fundamental_weaknesses: list[str] = fundamental.get("weaknesses", []) or []
        fundamental_summary: str = fundamental.get("summary", "") or ""
        fund_text: str = " ".join(fundamental_weaknesses) + " " + fundamental_summary
        if "fcf" in fund_text.lower() and (
            "negative" in fund_text.lower() or "weak" in fund_text.lower()
        ):
            financial_risk += 2

        fund_score_raw: Any = fundamental.get("score")
        fund_score: int = int(fund_score_raw) if fund_score_raw is not None else 5
        if fund_score <= 4:
            financial_risk += 1

    financial_risk = max(1, min(10, financial_risk))

    # --- Concentration risk (macro + technical signals)
    macro_headwinds: list[str] = macro.get("headwinds", []) or []
    tech_signal: str = str(technical.get("signal") or "HOLD")
    tech_strength_raw: Any = technical.get("signal_strength")
    tech_strength: int = int(tech_strength_raw) if tech_strength_raw is not None else 5

    concentration_risk: int = 3  # base
    if len(macro_headwinds) >= 3:
        concentration_risk += 2
    elif len(macro_headwinds) >= 1:
        concentration_risk += 1
    if tech_signal == "SELL" and tech_strength >= 6:
        concentration_risk += 2
    concentration_risk = max(1, min(10, concentration_risk))

    # --- Composite (weighted average)
    raw_composite: float = (
        governance_risk * 0.30
        + regulatory_risk * 0.25
        + financial_risk * 0.30
        + concentration_risk * 0.15
    )
    risk_score: int = max(1, min(10, round(raw_composite)))

    return {
        "governance_risk": governance_risk,
        "regulatory_risk": regulatory_risk,
        "financial_risk": financial_risk,
        "concentration_risk": concentration_risk,
        "risk_score": risk_score,
    }


def _determine_concentration_flags(
    fundamental: dict[str, Any],
    macro: dict[str, Any],
    technical: dict[str, Any],
) -> list[str]:
    """
    Identify concrete concentration risk flags from research data.

    Returns a list of 0-5 specific flags.
    """
    flags: list[str] = []

    macro_headwinds: list[str] = macro.get("headwinds", []) or []
    for headwind in macro_headwinds[:3]:
        flags.append(f"Macro headwind: {headwind}")

    sector_impact: str = str(macro.get("sector_impact") or "neutral")
    if sector_impact == "headwind":
        flags.append(
            "Macro economist classifies sector impact as headwind -- "
            "elevated sector concentration risk"
        )

    tech_signal: str = str(technical.get("signal") or "HOLD")
    tech_strength_raw: Any = technical.get("signal_strength")
    tech_strength: int = int(tech_strength_raw) if tech_strength_raw is not None else 5
    if tech_signal == "SELL" and tech_strength >= 6:
        flags.append(
            f"Technical analyst SELL signal (strength {tech_strength}/10) "
            "indicates price momentum risk"
        )

    # Check for high D/E as a concentration risk (leverage dependency)
    de_raw: Any = fundamental.get("debt_to_equity")
    if de_raw is not None:
        de_val: float = float(de_raw)
        if de_val > 1.5:
            flags.append(
                f"Debt/equity ratio of {de_val:.2f} creates leverage "
                "concentration risk in rising interest rate environments"
            )

    return flags[:5]


def _determine_risk_recommendation(risk_score: int) -> str:
    """
    Map composite risk_score to a Risk Officer recommendation.

    Band thresholds:
      1-3  -- low risk         -> proceed_with_caution
      4-6  -- moderate risk    -> monitor_closely
      7-10 -- high/extreme     -> avoid
    """
    if risk_score >= 7:
        return "avoid"
    if risk_score >= 4:
        return "monitor_closely"
    return "proceed_with_caution"


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _build_risk_prompt(
    company_name: str,
    ticker: str,
    fundamental: dict[str, Any],
    technical: dict[str, Any],
    sentiment: dict[str, Any],
    macro: dict[str, Any],
    scores: dict[str, Any],
    sentinel_flags: dict[str, list[str]],
) -> str:
    """
    Build the user-turn prompt sent to the LLM.

    The LLM receives pre-processed, structured data -- not raw JSON blobs.
    Deterministic scores and sentinel flags are pre-computed and included
    so the LLM can focus on narrative synthesis.
    """

    def _fmt(val: Any, suffix: str = "") -> str:
        if val is None:
            return "N/A"
        if isinstance(val, float):
            return f"{val:,.2f}{suffix}"
        return f"{val}{suffix}"

    # --- Fundamental snapshot
    fund_score: Any = fundamental.get("score", "N/A")
    de: Any = fundamental.get("debt_to_equity")
    current_ratio: Any = fundamental.get("current_ratio")
    roe: Any = fundamental.get("roe_pct")
    fcf: Any = fundamental.get("free_cash_flow_cr")
    fund_summary: str = fundamental.get("summary", "No summary available")
    fund_weaknesses: list[str] = fundamental.get("weaknesses", []) or []

    # --- Technical snapshot
    tech_signal: str = str(technical.get("signal", "N/A"))
    tech_strength: Any = technical.get("signal_strength", "N/A")
    rsi: Any = technical.get("rsi_14")
    price_vs_high: Any = technical.get("price_vs_52w_high_pct")
    tech_summary: str = technical.get("summary", "No summary available")

    # --- Sentiment snapshot
    sent_score: Any = sentiment.get("sentiment_score", "N/A")
    sent_label: str = str(sentiment.get("sentiment_label", "N/A"))
    red_flags: list[str] = sentiment.get("red_flags", []) or []
    red_flag_count: int = int(sentiment.get("red_flag_count") or 0)
    sent_summary: str = sentiment.get("summary", "No summary available")

    # --- Macro snapshot
    macro_env: str = str(macro.get("macro_environment", "N/A"))
    sector_impact: str = str(macro.get("sector_impact", "N/A"))
    headwinds: list[str] = macro.get("headwinds", []) or []
    repo_rate: Any = macro.get("rbi_repo_rate_pct")
    macro_summary: str = macro.get("summary", "No summary available")

    # --- Pre-computed scores
    risk_score: int = int(scores.get("risk_score", 5))
    gov_risk: int = int(scores.get("governance_risk", 5))
    reg_risk: int = int(scores.get("regulatory_risk", 5))
    fin_risk: int = int(scores.get("financial_risk", 5))
    conc_risk: int = int(scores.get("concentration_risk", 5))

    # --- Sentinel flags already found
    pre_fraud: list[str] = sentinel_flags.get("fraud_indicators", [])
    pre_reg: list[str] = sentinel_flags.get("regulatory_risks", [])
    pre_gov: list[str] = sentinel_flags.get("governance_flags", [])

    weaknesses_block: str = (
        "\n".join(f"  - {w}" for w in fund_weaknesses) or "  None reported"
    )
    red_flags_block: str = "\n".join(f"  - {f}" for f in red_flags) or "  None"
    headwinds_block: str = "\n".join(f"  - {h}" for h in headwinds) or "  None"
    pre_fraud_block: str = "\n".join(f"  - {f}" for f in pre_fraud) or "  None detected"
    pre_reg_block: str = "\n".join(f"  - {r}" for r in pre_reg) or "  None detected"
    pre_gov_block: str = "\n".join(f"  - {g}" for g in pre_gov) or "  None detected"

    return f"""Perform a comprehensive risk assessment for {company_name} ({ticker}).

PRE-COMPUTED RISK SCORES (do NOT change these -- they are deterministic):
  Composite risk score  : {risk_score}/10  (higher = riskier)
  Governance risk       : {gov_risk}/10
  Regulatory risk       : {reg_risk}/10
  Financial risk        : {fin_risk}/10
  Concentration risk    : {conc_risk}/10

--- FUNDAMENTAL ANALYST INPUTS ---
Fundamental quality score : {fund_score}/10
Debt/Equity               : {_fmt(de)}
Current Ratio             : {_fmt(current_ratio)}
ROE                       : {_fmt(roe, '%')}
Free Cash Flow            : Rs. {_fmt(fcf)} Cr
Weaknesses identified:
{weaknesses_block}
Summary: {fund_summary}

--- TECHNICAL ANALYST INPUTS ---
Signal         : {tech_signal} (strength {tech_strength}/10)
RSI-14         : {_fmt(rsi)}
Price vs 52w H : {_fmt(price_vs_high, '%')}
Summary: {tech_summary}

--- SENTIMENT ANALYST INPUTS ---
Sentiment score : {sent_score} ({sent_label})
Red flags found : {red_flag_count}
Red flags:
{red_flags_block}
Summary: {sent_summary}

--- MACRO ECONOMIST INPUTS ---
Macro environment : {macro_env}
Sector impact     : {sector_impact}
RBI repo rate     : {_fmt(repo_rate, '%')}
Headwinds:
{headwinds_block}
Summary: {macro_summary}

--- PRE-DETECTED SENTINEL FLAGS (keyword scan) ---
Fraud indicators:
{pre_fraud_block}
Regulatory risks:
{pre_reg_block}
Governance concerns:
{pre_gov_block}

Using all the above data, produce the JSON output as specified in the \
system prompt.  You must address every pre-detected sentinel flag -- \
either confirm it as a genuine risk or explain why it is a false positive.
Do not invent risks not supported by the data above."""


# ---------------------------------------------------------------------------
# Core agent logic (separated from LangGraph node for testability)
# ---------------------------------------------------------------------------


def _run_risk_analysis_core(
    analysis_id: str,
    company_name: str,
    ticker: str,
    fundamental: dict[str, Any],
    technical: dict[str, Any],
    sentiment: dict[str, Any],
    macro: dict[str, Any],
) -> RiskAnalysis:
    """
    Core Risk Officer logic.

    Separated from ``run_risk_analysis`` so it can be called directly
    in tests with controlled inputs (no LangGraph state required).

    Stage 1: Deterministic scoring from structured research data.
    Stage 2: LLM narrative synthesis for governance/fraud flags.

    Never raises -- on any failure returns RiskAnalysis with error set.

    Args:
        analysis_id:  UUID of the parent Analysis job.
        company_name: Human-readable company name.
        ticker:       Yahoo Finance ticker (e.g. 'TCS.NS').
        fundamental:  FundamentalAnalysis.model_dump() dict (may be empty).
        technical:    TechnicalAnalysis.model_dump() dict (may be empty).
        sentiment:    SentimentAnalysis.model_dump() dict (may be empty).
        macro:        MacroAnalysis.model_dump() dict (may be empty).

    Returns:
        RiskAnalysis Pydantic model (frozen, serialisable).
    """
    logger.info(
        "Risk Officer: starting analysis ticker=%s analysis=%s",
        ticker,
        analysis_id,
    )

    # --- Stage 1a: Collect all text for keyword scanning
    all_text: str = _collect_all_text(fundamental, technical, sentiment, macro)

    # --- Stage 1b: Sentinel keyword detection (pure, no LLM)
    sentinel_flags: dict[str, list[str]] = _extract_sentinel_flags(all_text, sentiment)

    # --- Stage 1c: Deterministic sub-scores and composite
    scores: dict[str, Any] = _score_risk(
        fundamental, technical, sentiment, macro, sentinel_flags
    )

    # --- Stage 1d: Concentration risk flags (pure)
    concentration_flags: list[str] = _determine_concentration_flags(
        fundamental, macro, technical
    )

    # --- Stage 1e: Recommendation from composite score
    risk_score: int = int(scores["risk_score"])
    risk_recommendation: str = _determine_risk_recommendation(risk_score)

    # --- Stage 2: LLM narrative synthesis
    logger.info("Risk Officer: invoking LLM ticker=%s", ticker)

    governance_flags: list[str] = list(sentinel_flags.get("governance_flags", []))
    regulatory_risks: list[str] = list(sentinel_flags.get("regulatory_risks", []))
    fraud_indicators: list[str] = list(sentinel_flags.get("fraud_indicators", []))
    summary: str = ""

    try:
        llm = get_llm()
        prompt = _build_risk_prompt(
            company_name=company_name,
            ticker=ticker,
            fundamental=fundamental,
            technical=technical,
            sentiment=sentiment,
            macro=macro,
            scores=scores,
            sentinel_flags=sentinel_flags,
        )
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        response = llm.invoke(messages)
        raw_text: str = (
            response.content if hasattr(response, "content") else str(response)
        )

        # Strip any accidental markdown fences the LLM adds
        cleaned: str = re.sub(r"```(?:json)?|```", "", raw_text).strip()
        parsed: dict[str, Any] = json.loads(cleaned)

        # Merge LLM output with pre-detected sentinel flags (union, deduplicated)
        llm_gov: list[str] = parsed.get("governance_flags", []) or []
        llm_reg: list[str] = parsed.get("regulatory_risks", []) or []
        llm_fraud: list[str] = parsed.get("fraud_indicators", []) or []

        def _merge(pre: list[str], llm_out: list[str]) -> list[str]:
            seen: set[str] = set()
            merged: list[str] = []
            for item in pre + llm_out:
                key: str = item[:60].lower()
                if key not in seen:
                    seen.add(key)
                    merged.append(item)
            return merged[:5]

        governance_flags = _merge(governance_flags, llm_gov)
        regulatory_risks = _merge(regulatory_risks, llm_reg)
        fraud_indicators = _merge(fraud_indicators, llm_fraud)

        llm_conc: list[str] = parsed.get("concentration_risks", []) or []
        for item in llm_conc:
            if item not in concentration_flags:
                concentration_flags.append(item)
        concentration_flags = concentration_flags[:5]

        llm_rec: str = str(parsed.get("risk_recommendation", ""))
        if llm_rec in (
            "proceed_with_caution",
            "monitor_closely",
            "avoid",
        ):
            risk_recommendation = llm_rec

        summary = str(parsed.get("summary", ""))

    except Exception as exc:
        logger.exception("LLM call failed in Risk Officer for %s: %s", ticker, exc)
        summary = (
            f"{company_name} has a composite risk score of {risk_score}/10. "
            f"Governance risk {scores['governance_risk']}/10, "
            f"regulatory risk {scores['regulatory_risk']}/10, "
            f"financial risk {scores['financial_risk']}/10. "
            f"LLM narrative synthesis failed -- review sentinel flags manually."
        )

    # --- Build critical_flags (all flags combined into one list)
    all_flags: list[str] = (
        governance_flags + regulatory_risks + fraud_indicators + concentration_flags
    )

    # Critical = any fraud indicator OR any flag with a regulatory keyword
    #
    # Uses the same word-boundary _contains_keyword helper as the rest of
    # this module's sentinel detection (T-095 follow-up) -- this call site
    # was still using plain `kw in flag_lower` substring containment, the
    # exact pre-patch pattern the T-095 fix eliminated everywhere else.
    # Also checks _sebi_action_present() directly since "sebi" itself is no
    # longer a literal entry in _REGULATORY_KEYWORDS (replaced by the
    # proximity match) -- a genuine SEBI regulatory action must still be
    # promoted to critical.
    critical_flags: list[str] = []
    for flag in all_flags:
        flag_lower: str = flag.lower()
        is_fraud: bool = any(
            _contains_keyword(kw, flag_lower) for kw in _FRAUD_KEYWORDS
        )
        is_high_reg: bool = any(
            _contains_keyword(kw, flag_lower) for kw in _REGULATORY_KEYWORDS
        ) or _sebi_action_present(flag_lower)
        if is_fraud or is_high_reg:
            critical_flags.append(flag)

    # All flags combined (for state["risk_flags"])
    risk_flags: list[str] = all_flags

    return RiskAnalysis(
        agent_name="risk_officer",
        analysis_id=analysis_id,
        company_name=company_name,
        ticker=ticker,
        risk_score=risk_score,
        governance_risk=int(scores["governance_risk"]),
        regulatory_risk=int(scores["regulatory_risk"]),
        financial_risk=int(scores["financial_risk"]),
        concentration_risk=int(scores["concentration_risk"]),
        risk_flags=risk_flags,
        critical_flags=critical_flags,
        risk_recommendation=risk_recommendation,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# LangGraph node entry point
# ---------------------------------------------------------------------------


@traced_agent("risk_officer")
def run_risk_analysis(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph node function for the Risk Officer agent.

    Reads from InvestmentState:
      - job_id        -> analysis_id for the output model
      - company_name  -> human-readable company name
      - ticker        -> Yahoo Finance ticker
      - fundamental   -> FundamentalAnalysis.model_dump() dict (may be None)
      - technical     -> TechnicalAnalysis.model_dump() dict (may be None)
      - sentiment     -> SentimentAnalysis.model_dump() dict (may be None)
      - macro         -> MacroAnalysis.model_dump() dict (may be None)

    Writes to InvestmentState:
      - risk          -> RiskAnalysis.model_dump()
      - risk_flags    -> flat list of all flags (for downstream agents)
      - critical_flags -> subset of severe flags (for Portfolio Manager)

    Never raises -- on failure, ``risk["error"]`` is set.

    Args:
        state: InvestmentState dict (LangGraph passes the full state).

    Returns:
        Dict with keys 'risk', 'risk_flags', 'critical_flags'.
    """
    analysis_id: str = state.get("job_id", "unknown")
    company_name: str = state.get("company_name", "Unknown Company")
    ticker: str = state.get("ticker", "")

    if not ticker:
        logger.error("run_risk_analysis called with empty ticker")
        result = RiskAnalysis(
            agent_name="risk_officer",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker="UNKNOWN",
            risk_score=5,
            governance_risk=5,
            regulatory_risk=5,
            financial_risk=5,
            concentration_risk=5,
            error="ticker field is missing from InvestmentState",
        )
        return {
            "risk": result.model_dump(),
            "risk_flags": [],
            "critical_flags": [],
        }

    # Safely retrieve research agent dicts (default to empty dict)
    fundamental: dict[str, Any] = dict(state.get("fundamental") or {})
    technical: dict[str, Any] = dict(state.get("technical") or {})
    sentiment: dict[str, Any] = dict(state.get("sentiment") or {})
    macro: dict[str, Any] = dict(state.get("macro") or {})

    # Preserve flags written by upstream nodes (error_handler,
    # sentiment_escalation) so they are not overwritten.
    # Risk Officer ADDS its own flags on top of any existing ones.
    upstream_risk_flags: list[str] = list(state.get("risk_flags") or [])
    upstream_critical_flags: list[str] = list(state.get("critical_flags") or [])

    try:
        result = _run_risk_analysis_core(
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            fundamental=fundamental,
            technical=technical,
            sentiment=sentiment,
            macro=macro,
        )
    except Exception as exc:
        logger.exception("Unhandled error in Risk Officer node: ticker=%s", ticker)
        result = RiskAnalysis(
            agent_name="risk_officer",
            analysis_id=analysis_id,
            company_name=company_name,
            ticker=ticker,
            risk_score=5,
            governance_risk=5,
            regulatory_risk=5,
            financial_risk=5,
            concentration_risk=5,
            error=f"Unhandled agent error: {exc}",
        )

    # Merge: upstream flags first, then Risk Officer flags (deduplicated).
    def _merge_flags(upstream: list[str], agent: list[str]) -> list[str]:
        seen: set[str] = set(upstream)
        merged: list[str] = list(upstream)
        for flag in agent:
            if flag not in seen:
                seen.add(flag)
                merged.append(flag)
        return merged

    merged_risk_flags = _merge_flags(upstream_risk_flags, result.risk_flags)
    merged_critical_flags = _merge_flags(upstream_critical_flags, result.critical_flags)

    return {
        "risk": result.model_dump(),
        "risk_flags": merged_risk_flags,
        "critical_flags": merged_critical_flags,
    }
