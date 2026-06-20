# scripts/run_full_analysis_infosys.py
"""
AIRP -- Run one full end-to-end analysis and produce a real memo PDF.

This is a one-off manual script (see scripts/README.md), not part of
the application. It exists because Phase 5 (the FastAPI backend that
will trigger analyses over HTTP) has not been built yet -- the only
way to exercise the complete LangGraph pipeline today is to invoke
build_graph() directly from a script like this one.

What it does
------------
1. Builds the compiled LangGraph pipeline (the same build_graph() the
   FastAPI backend will call in Phase 5).
2. Creates a fresh InvestmentState for one company via
   make_initial_state().
3. Invokes the graph synchronously, letting all 8 agents run for
   real: the 4 research agents in parallel, the debate loop with the
   Contrarian Investor, the Risk Officer, the Valuation Agent, and
   finally the Portfolio Manager's verdict.
4. Prints the final verdict and the path to the generated PDF
   (state["memo_pdf_path"], written by pdf_export_node / T-043).

Usage
-----
    set ENVIRONMENT=development   (Windows CMD; do NOT chain with &&)
    python -m scripts.run_full_analysis_infosys

Defaults to Infosys (INFY.NS) -- a separate ticker from
scripts/run_full_analysis.py (which defaults to TCS.NS), so the two
scripts don't compete for the same yFinance request budget if you
have been rate-limited on one ticker recently.

Edit COMPANY_NAME / TICKER / EXCHANGE below to point at a different
NSE/BSE stock before running.

Requirements
------------
- A real LLM key configured in .env (LLM_PROVIDER=groq + GROQ_API_KEY
  is the cheapest/fastest option for a demo run; Claude works too but
  is intended for the final demo phase per AIRP standards).
- ENVIRONMENT must NOT be "test" -- persist_state is patched to a
  no-op only in tests, and FEATURE_PDF_ENABLED / WeasyPrint need to
  actually run here, not be mocked.
- WeasyPrint's system libraries (Pango, Cairo, GDK-Pixbuf) installed
  locally -- see docs/week-12/T-043-pdf-export.md section 3 for the
  one-time setup per OS. Without them, every other agent still runs
  correctly; only memo_pdf_path will come back as None.
- This makes REAL calls to yFinance, NewsAPI, Alpha Vantage,
  Screener.in, and your configured LLM provider -- it is not a unit
  test and is not mocked. Expect it to take well under the pipeline's
  <90s acceptance target for a single company.

Design decisions
----------------
* NO ``from __future__ import annotations`` -- AIRP rule.
* Plain ASCII section comments (# ---).
* No bare ``# type: ignore``.
* Not imported anywhere else in the codebase -- intentionally a
  standalone CLI entry point, consistent with the other scripts/
  utilities documented in scripts/README.md.
"""

import logging
import sys
import uuid
from typing import Any

from backend.graph.graph import build_graph
from backend.graph.state import InvestmentState, make_initial_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("scripts.run_full_analysis_infosys")

# ---------------------------------------------------------------------------
# Edit these three values to analyse a different company
# ---------------------------------------------------------------------------

COMPANY_NAME = "Infosys"
TICKER = "INFY.NS"
EXCHANGE = "NSE"


def main() -> int:
    """Run one full AIRP analysis end-to-end and report the outcome."""
    job_id: str = str(uuid.uuid4())

    logger.info(
        "Starting full AIRP analysis: company=%r ticker=%r job_id=%s",
        COMPANY_NAME,
        TICKER,
        job_id,
    )

    initial_state: InvestmentState = make_initial_state(
        job_id=job_id,
        company_name=COMPANY_NAME,
        ticker=TICKER,
        exchange=EXCHANGE,
        raw_query=f"Should I invest in {COMPANY_NAME}?",
        requested_by="manual-script",
    )

    graph: Any = build_graph()

    logger.info("Invoking compiled graph -- this calls real APIs and the LLM...")
    final_state: dict[str, Any] = graph.invoke(initial_state)

    # -- Report the outcome ------------------------------------------------
    decision: dict[str, Any] = final_state.get("decision") or {}
    verdict: str = str(decision.get("verdict", "UNKNOWN"))
    conviction: Any = decision.get("conviction_score", "n/a")
    memo_pdf_path: Any = final_state.get("memo_pdf_path")
    memo_markdown: Any = final_state.get("memo_markdown")
    pipeline_error: Any = final_state.get("pipeline_error")

    print("\n" + "=" * 72)
    print(f"Company:          {COMPANY_NAME} ({TICKER})")
    print(f"Job ID:           {job_id}")
    print(f"Status:           {final_state.get('status', 'unknown')}")
    print(f"Verdict:          {verdict}")
    print(f"Conviction score: {conviction}/10")
    print(f"Memo (Markdown):  {'present' if memo_markdown else 'MISSING'}")
    print(f"Memo (PDF path):  {memo_pdf_path or 'None -- check WeasyPrint setup'}")
    if pipeline_error:
        print(f"Pipeline error:   {pipeline_error}")
    print("=" * 72 + "\n")

    # -- Contrarian Investor raw output -------------------------------------
    # This is the actual ContrarianReport the agent produced, before the
    # Portfolio Manager folds it into the memo's prose "Bear Case" section.
    # Printed separately, in a clean screenshot-friendly block, since this
    # is the part of the pipeline most worth showing people: a specific,
    # numbered list of counter-arguments an AI agent generated against the
    # other agents' conclusions.
    contrarian: dict[str, Any] = final_state.get("contrarian") or {}
    if contrarian and not contrarian.get("error"):
        print("=" * 72)
        print("CONTRARIAN INVESTOR -- raw agent output")
        print("=" * 72)
        bear_conviction: Any = contrarian.get("bear_conviction", "n/a")
        print(f"\nBear conviction: {bear_conviction}/10\n")

        strongest: str = str(contrarian.get("strongest_argument", "")).strip()
        if strongest:
            print("Strongest argument:")
            print(f"  {strongest}\n")

        challenged: list[Any] = contrarian.get("challenged_agents") or []
        if challenged:
            print(f"Challenged agents: {', '.join(str(a) for a in challenged)}\n")

        counter_args: list[Any] = contrarian.get("counter_arguments") or []
        if counter_args:
            print("Counter-arguments:")
            for i, arg in enumerate(counter_args, start=1):
                print(f"  {i}. {arg}")
            print()

        overlooked: list[Any] = contrarian.get("overlooked_risks") or []
        if overlooked:
            print("Overlooked risks:")
            for i, risk in enumerate(overlooked, start=1):
                print(f"  {i}. {risk}")
            print()

        summary: str = str(contrarian.get("summary", "")).strip()
        if summary:
            print("Summary:")
            print(f"  {summary}\n")

        print("=" * 72 + "\n")
    elif contrarian.get("error"):
        logger.warning(
            "Contrarian agent returned an error, nothing to print: %s",
            contrarian.get("error"),
        )
    else:
        logger.warning("No contrarian output found in final_state.")

    if memo_pdf_path:
        logger.info("Open the PDF at: %s", memo_pdf_path)
        return 0

    logger.warning(
        "memo_pdf_path is None. memo_markdown is still readable in "
        "final_state['memo_markdown'] above -- the PDF step specifically "
        "degrades gracefully (see backend/services/pdf_export.py). "
        "Check that FEATURE_PDF_ENABLED=true and that WeasyPrint's "
        "system libraries are installed (docs/week-12/T-043-pdf-export.md)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())