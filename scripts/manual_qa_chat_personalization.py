# scripts/manual_qa_chat_personalization.py
"""
AIRP -- Manual QA script for T-106 (personalization via user_preferences).

This is a one-off manual script (see scripts/README.md), not part of
the application. T-106's acceptance criteria require proving, in
manual QA, that the assistant's tone "visibly adapts" once a risk
appetite is known -- something unit tests (mocked LLM) cannot show,
the same reasoning scripts/manual_qa_chat_llm.py's own docstring gives
for T-102's guardrail QA script. This script is that script's sibling
for T-106: same fixed-context, real-LLM-call approach, extended to
also exercise extract_preferences/build_personalization_instruction
end to end.

What it demonstrates
---------------------
1. ASK ONCE: turn 1 uses no risk_appetite/preferred_sectors at all
   (simulating a brand-new user's very first message) and prints
   whether the reply naturally asks about risk appetite/sectors --
   this is genuinely up to the real LLM's judgement (the instruction
   says "if a natural moment arises", not "always"), so this step
   reports what happened rather than asserting a pass/fail.
2. EXTRACTION: the user's turn-2 reply ("I'm a conservative investor,
   mostly interested in IT and FMCG") is run through the REAL
   backend.services.preference_extractor.extract_preferences -- the
   exact function backend/routers/chat_stream.py calls on every turn
   -- and the recognised risk_appetite/preferred_sectors are printed,
   proving the deterministic extractor actually recognises this
   phrasing (not just that unit tests with hand-picked fixtures do).
3. TONE ADAPTATION: turns 3a and 3b send the IDENTICAL question
   ("Should I be worried about the risks in this analysis?") against
   the SAME fixed context, once with risk_appetite="conservative" and
   once with risk_appetite="aggressive" -- a human reader compares the
   two real replies side by side to confirm the tone/emphasis visibly
   differs (downside-focused vs. growth-focused), which is exactly
   this task's "tone visibly adapts in manual QA" acceptance criterion.
4. VERDICT INDEPENDENCE: both 3a and 3b replies are scanned for the
   fixed context's own verdict/conviction/price-target figures (BUY,
   conviction 8/10, Rs 4,250) to confirm those numbers are either
   absent or, if present, appear VERBATIM and IDENTICALLY in both
   replies -- a crude but genuine sanity check that personalization
   never produced a different verdict-shaped number between the two
   runs. Like T-102's script, this is a keyword flag for a human to
   double check, not a substitute for reading both replies.

Usage
-----
    set ENVIRONMENT=development   (Windows CMD; do NOT chain with &&)
    python -m scripts.manual_qa_chat_personalization

Requirements
------------
- A real LLM key configured in .env (LLM_PROVIDER=groq + GROQ_API_KEY
  is the default AIRP dev provider; LLM_PROVIDER=anthropic works too).
- Makes REAL calls to your configured LLM provider -- not a unit test,
  not mocked, not run in CI. Costs a handful of Groq/Claude requests.

Design decisions
----------------
* NO ``from __future__ import annotations`` -- AIRP rule.
* Plain ASCII section comments (# ---).
* No bare ``# type: ignore``.
* Not imported anywhere else in the codebase -- a standalone CLI entry
  point, consistent with scripts/manual_qa_chat_llm.py and
  scripts/run_full_analysis.py.
"""

import logging
import sys

from backend.services.chat_llm import ChatLLMError, invoke_chat
from backend.services.preference_extractor import extract_preferences

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixed grounded context -- same shape as manual_qa_chat_llm.py's own
# FAKE_TCS_CONTEXT, reused here so both scripts' transcripts are
# directly comparable and this script has no dependency on a live
# database or a real completed analysis.
# ---------------------------------------------------------------------------

FAKE_TCS_CONTEXT = """\
Analysis of Tata Consultancy Services (TCS.NS), analysis_id=qa-fixture.

## Fundamental Analyst
Score: 9/10 (data quality: full, based on 4 of 4 years available)
Revenue growth: 12.40% YoY, 13.70% 3-year CAGR
Margins: gross 45.20%, operating 24.10%, net 19.30%
Summary: TCS demonstrates exceptional fundamental quality with
consistent double-digit growth and industry-leading ROE.

## Risk Officer
Overall risk score: 3/10
Risk flags: none critical
Recommendation: Low governance and regulatory risk given TCS's
long-standing compliance track record.

## Portfolio Manager Decision
Verdict: BUY (conviction 8/10, time horizon: 12-18 months)
Price target: Rs 4,250
Executive summary: TCS combines best-in-class fundamentals with a
constructive technical setup and low governance risk. The committee
rates this a high-conviction BUY.
Bull case: Consistent double-digit revenue growth, industry-leading
margins, and a clean balance sheet support continued outperformance.
Bear case: Valuation is not cheap; a slowdown in discretionary IT
spending among US/EU clients is the primary risk to the thesis.
Key risks: US/EU client budget cuts; INR appreciation compressing
export margins.
Debate rounds used: 2
"""

#: The exact figures a reply must never CHANGE (it may omit them, or
#: repeat them verbatim, but never state a different number) --
#: the concrete keyword check behind "verdict independence" (step 4).
_VERDICT_BEARING_PHRASES = ("BUY", "conviction 8/10", "Rs 4,250", "4,250")


def _print_header(title: str) -> None:
    print("=" * 78)
    print(title)
    print("=" * 78)
    print()


def _run_turn(
    history: list[dict[str, str]],
    label: str,
    user_message: str,
    risk_appetite: str | None = None,
    preferred_sectors: list[str] | None = None,
) -> str:
    print(f"--- Turn: {label} ---")
    print(f"USER: {user_message}")
    if risk_appetite is not None or preferred_sectors:
        print(
            f"  (personalization context: risk_appetite={risk_appetite!r}, "
            f"preferred_sectors={preferred_sectors!r})"
        )
    print()
    try:
        reply = invoke_chat(
            history,
            user_message,
            response_style="detailed",
            context=FAKE_TCS_CONTEXT,
            risk_appetite=risk_appetite,
            preferred_sectors=preferred_sectors,
        )
    except ChatLLMError as exc:
        logger.error("manual_qa_chat_personalization: turn %r failed: %s", label, exc)
        print(f"ASSISTANT: <ChatLLMError: {exc}>\n")
        sys.exit(1)

    print(f"ASSISTANT: {reply}\n")
    return reply


def _check_verdict_bearing_phrases_match(reply_a: str, reply_b: str) -> None:
    """Step 4's sanity check -- see module docstring."""
    print("--- Verdict-independence check (turns 3a vs 3b) ---")
    any_mismatch = False
    for phrase in _VERDICT_BEARING_PHRASES:
        in_a = phrase.lower() in reply_a.lower()
        in_b = phrase.lower() in reply_b.lower()
        if in_a != in_b:
            any_mismatch = True
            print(
                f"  [REVIEW] '{phrase}' appears in one reply but not the "
                f"other (in 3a={in_a}, in 3b={in_b}) -- read both replies "
                f"carefully before pasting into the PR."
            )
    if not any_mismatch:
        print(
            "  [OK] every verdict-bearing figure checked appears "
            "identically (or not at all) in both replies.\n"
        )
    else:
        print()


def main() -> None:
    _print_header("T-106 Manual QA -- AIRP Assistant personalization")

    # --- Step 1: ASK ONCE (brand-new user, nothing known yet) ---------
    print("Step 1: brand-new user, no risk_appetite/preferred_sectors known yet.\n")
    turn1_history: list[dict[str, str]] = []
    turn1_reply = _run_turn(
        turn1_history,
        "nothing known yet",
        "Tell me about the TCS analysis.",
    )
    asked = any(
        phrase in turn1_reply.lower()
        for phrase in (
            "risk appetite",
            "risk tolerance",
            "sectors are you",
            "which sectors",
        )
    )
    outcome = "OK -- assistant asked" if asked else "NOTE -- assistant did not ask"
    print(
        f"  [{outcome}] "
        "the instruction says 'if a natural moment arises', not "
        "'always' -- either outcome is acceptable; read the reply to "
        "judge whether it felt natural.\n"
    )

    # --- Step 2: EXTRACTION (real preference_extractor, real phrasing) --
    print("Step 2: does the real extractor recognise a natural self-description?\n")
    sample_message = (
        "I'm a conservative investor, and I'm mostly interested in IT and FMCG stocks."
    )
    extraction = extract_preferences(sample_message)
    print(f"  Message: {sample_message!r}")
    print(f"  Extracted risk_appetite: {extraction.risk_appetite!r}")
    print(f"  Extracted preferred_sectors: {extraction.preferred_sectors!r}")
    found_risk_appetite = extraction.risk_appetite == "conservative"
    found_sector = "IT" in extraction.preferred_sectors
    if found_risk_appetite and found_sector:
        print("  [OK] extractor recognised both the risk appetite and a sector.\n")
    else:
        print("  [REVIEW] extractor did not recognise the expected fields.\n")

    # --- Step 3: TONE ADAPTATION (same question, two risk appetites) ----
    print("Step 3: identical question, conservative vs. aggressive risk appetite.\n")
    same_question = "Should I be worried about the risks in this analysis?"

    reply_3a = _run_turn(
        [],
        "3a -- conservative",
        same_question,
        risk_appetite="conservative",
    )
    reply_3b = _run_turn(
        [],
        "3b -- aggressive",
        same_question,
        risk_appetite="aggressive",
    )
    print(
        "  Read 3a and 3b above side by side: 3a should lean toward "
        "downside risk / capital preservation in its framing, 3b toward "
        "growth catalysts -- confirm this yourself; it is the direct "
        "evidence for this task's 'tone visibly adapts' criterion.\n"
    )

    # --- Step 4: VERDICT INDEPENDENCE ------------------------------------
    _check_verdict_bearing_phrases_match(reply_3a, reply_3b)

    print("=" * 78)
    print("Copy Steps 1-4 above into the PR's manual QA transcript section.")
    print("Read every ASSISTANT reply yourself before pasting -- the")
    print("[REVIEW]/[OK] flags are keyword sanity checks, not a substitute")
    print("for reading the actual text.")
    print("=" * 78)


if __name__ == "__main__":
    main()
