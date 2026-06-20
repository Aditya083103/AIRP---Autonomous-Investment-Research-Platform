# AIRP -- Investment Pipeline Graph Diagram

> **Auto-generated** by `backend/graph/graph_visualisation.py`
> on every `build_graph()` call.  **Do not edit manually** -- your
> changes will be overwritten on the next graph compile.
>
> Generated: 2026-06-20 05:10:43 UTC

## Overview

The diagram below shows the complete AIRP LangGraph StateGraph topology
as of the most recent graph compilation.  All 12 nodes and their edges
are shown including the parallel research fan-out, the conditional routing
join, the debate loop, and the sequential tail.

Node categories:

- **planner** -- Pipeline entry point; validates state and fans out to research agents
- **fundamental_analyst, technical_analyst, sentiment_analyst,
  macro_economist** -- Four research agents; run in parallel (T-031)
- **research_join** -- Join choke-point; route_after_research fires exactly once (T-032)
- **error_handler** -- Catches failed fetch_financials; marks pipeline degraded (T-032)
- **sentiment_escalation** -- Flags severely negative news environment (T-032)
- **contrarian_investor** -- Challenges every bullish thesis; drives the debate loop
- **risk_officer, valuation_agent, portfolio_manager** -- Final analysis sequence
- **report_generator** -- Renders the Investment Memo (Markdown) from the
  Portfolio Manager's decision
- **pdf_export** -- Converts the Markdown memo to a branded PDF via
  WeasyPrint; final node before END

## Graph

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	planner(planner)
	fundamental_analyst(fundamental_analyst)
	technical_analyst(technical_analyst)
	sentiment_analyst(sentiment_analyst)
	macro_economist(macro_economist)
	research_join(research_join)
	error_handler(error_handler)
	sentiment_escalation(sentiment_escalation)
	contrarian_investor(contrarian_investor)
	debate_loop(debate_loop)
	risk_officer(risk_officer)
	valuation_agent(valuation_agent)
	portfolio_manager(portfolio_manager)
	report_generator(report_generator)
	pdf_export(pdf_export)
	__end__([<p>__end__</p>]):::last
	__start__ --> planner;
	contrarian_investor --> debate_loop;
	error_handler --> contrarian_investor;
	fundamental_analyst --> research_join;
	macro_economist --> research_join;
	pdf_export --> __end__;
	portfolio_manager --> report_generator;
	report_generator --> pdf_export;
	risk_officer --> valuation_agent;
	sentiment_analyst --> research_join;
	sentiment_escalation --> contrarian_investor;
	technical_analyst --> research_join;
	valuation_agent --> portfolio_manager;
	planner -.-> __end__;
	planner -.-> fundamental_analyst;
	planner -.-> technical_analyst;
	planner -.-> sentiment_analyst;
	planner -.-> macro_economist;
	research_join -. &nbsp;error&nbsp; .-> error_handler;
	research_join -. &nbsp;escalate_sentiment&nbsp; .-> sentiment_escalation;
	research_join -. &nbsp;proceed&nbsp; .-> contrarian_investor;
	debate_loop -. &nbsp;debate_again&nbsp; .-> contrarian_investor;
	debate_loop -. &nbsp;proceed&nbsp; .-> risk_officer;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

## Node Count

Total nodes: 15

## Edge Notes

- Planner uses the LangGraph Send API to fan out to all 4 research agents
  **simultaneously** in the same super-step.
- All 4 research agents have **direct edges** to `research_join` (not to
  `contrarian_investor` directly) so that conditional routing fires exactly
  once after the parallel join barrier.
- The `contrarian_investor` self-loop (debate round) fires when
  `bear_conviction >= 7` and fewer than 2 debate rounds have completed.
- `error_handler` and `sentiment_escalation` both edge unconditionally to
  `contrarian_investor` after writing their state flags.
