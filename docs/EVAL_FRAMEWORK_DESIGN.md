# AIRP — LangSmith Evaluation Framework Design

> **Phase 11 (Evaluation), T-067.** This is a **design document**: it defines
> the eval criteria, the datasets each eval needs, the grading rubric, and the
> LangSmith wiring plan for T-068–T-071. It does not itself implement any
> evaluator — implementation is intentionally split across the four build
> tasks below so each can land as its own reviewable PR.
>
> **A note on the filename.** The task's acceptance criteria says
> `docs/EVALUATION.md`, but that path is already taken by the Phase 8
> Verdict Accuracy Tracker methodology doc (T-087–T-093) — a different,
> already-shipped kind of evaluation (post-hoc market-outcome scoring of live
> verdicts, not pre-release LangSmith test suites). Overwriting it would
> destroy that documentation. This design doc lives at
> `docs/EVAL_FRAMEWORK_DESIGN.md` instead, and is the direct input to T-072
> ("Write EVALUATION.md"), which is a separate, later task in the same phase
> and is the right place to decide how the two `EVALUATION*.md` documents
> relate (e.g. cross-link, or merge under one file with two clearly
> separated parts). See [§6](#6-naming-and-sequencing-note) for the full
> reasoning.

---

## Table of Contents

1. [Why this exists](#1-why-this-exists)
2. [Scope: what T-067 designs vs. what T-068–T-071 build](#2-scope-what-t-067-designs-vs-what-t-068t-071-build)
3. [Eval criteria, datasets, and rubrics per agent](#3-eval-criteria-datasets-and-rubrics-per-agent)
   - [3.1 Fundamental accuracy (T-068)](#31-fundamental-accuracy-t-068)
   - [3.2 Sentiment direction (T-069)](#32-sentiment-direction-t-069)
   - [3.3 Contrarian novelty / debate quality (T-070)](#33-contrarian-novelty--debate-quality-t-070)
   - [3.4 Memo completeness](#34-memo-completeness)
   - [3.5 Latency <90s (T-071)](#35-latency-90s-t-071)
4. [LangSmith wiring plan](#4-langsmith-wiring-plan)
5. [Grading scale summary](#5-grading-scale-summary)
6. [Naming and sequencing note](#6-naming-and-sequencing-note)
7. [Open questions for T-068–T-071](#7-open-questions-for-t-068t-071)

---

## 1. Why this exists

Every agent in the 8-agent committee already returns a strictly-typed
Pydantic model (`backend/agents/output_models.py`) and every node is already
wrapped in LangSmith tracing (`backend/agents/tracing.py`, T-026). What's
missing is the second half of an eval story: **datasets of known-answer
inputs**, and **evaluator functions that grade a run's output against those
known answers**, registered as LangSmith experiments so a regression shows up
as a failing eval run, not as a recruiter noticing a wrong-looking memo in a
demo.

This document is the design pass required before writing any evaluator code:
for each of the five criteria named in the task description — fundamental
accuracy, sentiment direction, contrarian novelty, memo completeness, and
latency <90s — it fixes exactly what is being measured, what the input
dataset looks like, how a run is graded, and what LangSmith artifact each
build task produces. T-068–T-071 implement against this document; nothing in
it should need to change once those tasks start, only the code that
satisfies it.

## 2. Scope: what T-067 designs vs. what T-068–T-071 build

| Task | Owns | Grounded in |
| --- | --- | --- |
| **T-067 (this doc)** | Criteria definitions, dataset shape, rubric, grading scale for every agent | `output_models.py` schemas, `tracing.py` tagging contract |
| **T-068** | Fundamental Analyst eval — 5 companies, ground-truth score comparison | [§3.1](#31-fundamental-accuracy-t-068) |
| **T-069** | Sentiment Agent eval — directional accuracy + red-flag detection | [§3.2](#32-sentiment-direction-t-069) |
| **T-070** | Debate quality eval — Contrarian novelty, non-repetition, PM engagement | [§3.3](#33-contrarian-novelty--debate-quality-t-070) |
| **T-071** | End-to-end latency eval — p50/p95, per-node breakdown | [§3.5](#35-latency-90s-t-071) |
| **T-072** | `EVALUATION.md` — writes up the *results* of running T-068–T-071 against this design, plus known failure modes | This doc's rubrics, plus real LangSmith run data |

Memo completeness ([§3.4](#34-memo-completeness)) is deliberately **not**
assigned its own T-068–T-071 slot in the Excel plan — it is a structural
check, not a judged-correctness eval, so it is designed here as a shared
assertion helper any of T-068–T-071's LangSmith experiments can import
against `InvestmentDecision`, rather than a fifth standalone build task.

## 3. Eval criteria, datasets, and rubrics per agent

Every eval in this framework follows the same three-part shape, matching how
LangSmith itself models an experiment:

1. **Dataset** — a fixed set of `(inputs, reference_outputs)` examples,
   version-controlled as a JSON fixture under `backend/tests/eval_fixtures/`
   and uploaded to a named LangSmith dataset (one dataset per agent).
2. **Target function** — the actual agent node function under test, invoked
   with `inputs` and producing the Pydantic output model.
3. **Evaluator function(s)** — pure functions of `(run, example) -> score`
   registered with `langsmith.evaluate()`, each returning one named metric in
   the grading scale below.

### 3.1 Fundamental accuracy (T-068)

**What's being measured.** Whether `FundamentalAnalysis.score` (1–10,
`output_models.py`) agrees directionally with a known analyst-consensus
rating for the same company.

**Dataset.** 5 NSE-listed companies spanning a deliberate quality spread —
not 5 similar large-caps — so the eval can't pass by always guessing
"medium":

| Company (illustrative) | Ground-truth bucket | Rationale for inclusion |
| --- | --- | --- |
| A large, high-quality IT exporter | Strong (8–10) | Consistent margins, low debt — should score high |
| A stable, profitable FMCG major | Strong (7–9) | Different sector, same "should score high" check |
| A mid-cap with average, unremarkable fundamentals | Neutral (4–6) | Tests the agent doesn't over- or under-shoot a middling company |
| A leveraged, cyclical company with weak recent FCF | Weak (2–4) | Should score low — checks the agent isn't reflexively positive |
| A company with genuinely thin public financial data | N/A — `data_quality="insufficient"` | Checks the agent honestly returns `score=None` per its own contract, rather than fabricating a number |

Ground-truth buckets are set by hand from public screener data (Screener.in
consensus, or the same 5-metric basis the agent itself uses — revenue CAGR,
net margin, ROE, debt-to-equity, FCF margin) at dataset-authoring time, and
pinned as `reference_outputs` in the fixture — they are not re-derived at
eval time, so the eval stays stable even if the company's live financials
move between runs.

**Rubric.**

| Check | Pass condition |
| --- | --- |
| Directional agreement | `FundamentalAnalysis.score` falls in the same bucket (Strong/Neutral/Weak) as ground truth, or within 1 point of the bucket boundary |
| Honest abstention | The thin-data example returns `score=None` and `data_quality="insufficient"` — a confident wrong number here is a **hard fail**, not a partial-credit miss |
| Schema validity | Output parses as `FundamentalAnalysis` with no `error` set (for the 4 non-abstention examples) |

**Grading scale.** Binary pass/fail per example, aggregated as accuracy % —
matches T-068's own acceptance criterion (`accuracy >70% vs known analyst
consensus`).

### 3.2 Sentiment direction (T-069)

**What's being measured.** Whether `SentimentAnalysis.sentiment_score` /
`sentiment_label` and `red_flags` correctly capture the *direction* of known
news events, not their exact numeric score.

**Dataset.** 10 test news sets built from real, dated news windows with an
unambiguous direction (not requiring interpretation) — 4 clearly positive
(e.g. a large deal win, a strong earnings beat), 4 clearly negative (e.g. a
guidance cut, a leadership departure under a cloud), 2 genuinely mixed/flat.
Plus 3 known-scandal windows held out specifically for the red-flag check
(e.g. a well-documented regulatory action, governance controversy, or
accounting-restatement episode — chosen from public record, not fabricated).

**Rubric.**

| Check | Pass condition |
| --- | --- |
| Directional accuracy | `sentiment_label` is on the correct side of neutral (positive-labelled examples score `sentiment_score > 0`, negative examples `< 0`) for 8 of the 10 direction sets |
| Red-flag detection | `red_flag_count >= 1` and at least one string in `red_flags` is topically traceable to the known scandal, for all 3 scandal cases |
| No false alarms | The 2 flat/mixed sets and the 4 clean-positive sets do not spuriously populate `red_flags` |

**Grading scale.** Directional accuracy as a %, matching T-069's own
acceptance criterion (`>80% on 10 test news sets`); red-flag detection graded
separately as 3/3 required (all-or-nothing, since this is a safety-adjacent
check — a missed scandal is a worse failure mode than a missed sentiment
nuance).

### 3.3 Contrarian novelty / debate quality (T-070)

**What's being measured.** Two related but distinct things the task
description calls out: that the **Contrarian Investor** genuinely disagrees
rather than rubber-stamping consensus, and that the **debate loop as a
whole** produces non-repetitive, multi-agent engagement the Portfolio
Manager visibly uses.

**Dataset.** Not a fixed input/reference-output set like §3.1/§3.2 — this
eval runs against **live `InvestmentState` snapshots** captured from 3–5 full
pipeline runs across different companies (reusing runs already produced by
`backend/tests/integration/test_graph_integration.py`-style fixtures rather
than a new hand-authored dataset), since debate quality is a property of a
full multi-agent transcript, not a single agent's isolated output.

**Rubric.**

| Check | Pass condition | Grounded in |
| --- | --- | --- |
| Contrarian always disagrees | `ContrarianReport.counter_arguments` has ≥3 entries and `bear_conviction >= 1` (never an empty, rubber-stamp report) on every run | `output_models.py` — `ContrarianReport` |
| Novelty (not repetition) | No two entries in `counter_arguments` (or across `overlooked_risks`) are near-duplicate strings (checked via a simple token-overlap or embedding-similarity threshold, not exact match) | Task description: "no repetition" |
| Multi-agent engagement | `debate_rounds_used >= 1` and `agent_weights` (on `InvestmentDecision`) has non-zero weight for at least 2 distinct agents besides the Contrarian | `output_models.py` — `InvestmentDecision` |
| PM addresses the Contrarian | `InvestmentDecision.contrarian_response` is non-empty and is not a verbatim substring of `ContrarianReport.strongest_argument` (i.e. it engages with, not just echoes, the argument) | `output_models.py` — `contrarian_response` field docstring: "Every `ContrarianReport.strongest_argument` must be explicitly addressed" |

**Grading scale.** All-or-nothing pass/fail per run (this is a structural
"did the debate actually happen" check, not a graded quality score) —
matches T-070's acceptance criterion phrasing directly ("Contrarian always
disagrees; debate rounds non-repetitive; Portfolio Manager references debate
content").

### 3.4 Memo completeness

**What's being measured.** Whether the final `InvestmentDecision` — the
direct source of the Investment Memo PDF — actually has every section
populated with substantive content, not a placeholder or an empty string.

**Dataset.** Reuses the same 3–5 full-pipeline `InvestmentState` snapshots as
§3.3 (no separate dataset needed — this check runs against the same
`InvestmentDecision` those runs already produce).

**Rubric.** A single shared assertion helper (proposed location:
`backend/tests/eval_fixtures/memo_completeness.py`), reusable by any of
T-068–T-071's LangSmith experiments that touch `InvestmentDecision`:

| Field | Completeness check |
| --- | --- |
| `verdict`, `conviction_score` | Present, `verdict` in `{BUY, HOLD, SELL}` |
| `executive_summary`, `investment_thesis`, `bull_case`, `bear_case`, `risk_summary`, `valuation_summary` | Each non-empty and above a minimum length threshold (e.g. ≥40 characters) — long enough to be a real sentence, not a stub |
| `key_risks`, `key_catalysts` | Each has ≥1 entry |
| `contrarian_response` | Non-empty (also checked in [§3.3](#33-contrarian-novelty--debate-quality-t-070) for content quality; here just presence) |
| `price_target` | Either a real value or explicitly `None` — never an empty string masquerading as "no target" |

**Grading scale.** Binary pass/fail — a memo is "complete" only if every row
above passes; this feeds directly into T-072's `EVALUATION.md` as one line
item, not a separate task.

### 3.5 Latency <90s (T-071)

**What's being measured.** Full-pipeline wall-clock time against the
project's own stated target (README / Project Overview §2: "under 90
seconds"), broken down per node so a regression is attributable, not just
detectable.

**Dataset.** 3 companies chosen to cover a fast/typical/slow spread — e.g.
one with a short, cached news/financials fetch and one requiring an
uncached, cold-start Screener.in scrape — so the p50/p95 split in the rubric
means something.

**Rubric.**

| Metric | Target | Source |
| --- | --- | --- |
| p50 total pipeline latency | < 90s | Wall-clock across the 3 companies × N repeated runs |
| p95 total pipeline latency | < 120s | Same |
| Per-node breakdown | Every node's latency individually visible | Already free — `tracing.py`'s `@traced_agent` gives LangSmith automatic wall-clock timing per run; T-071 just needs to query and tabulate it, not add new instrumentation |
| Bottleneck identified | At least one node explicitly called out as the largest contributor, with a documented reason (e.g. "Screener.in scrape is uncached and synchronous") | Manual analysis step, written into T-071's own PR description and folded into T-072's `EVALUATION.md` |

**Grading scale.** Pass/fail against the p50/p95 numeric targets, plus a
required free-text bottleneck note — matches T-071's acceptance criterion
exactly.

## 4. LangSmith wiring plan

All four build tasks share one convention so their experiments show up
consistently in the LangSmith dashboard:

- **Dataset naming:** `airp-eval-<agent>` (e.g. `airp-eval-fundamental`,
  `airp-eval-sentiment`, `airp-eval-debate-quality`, `airp-eval-latency`) —
  created once per task via `langsmith.Client().create_dataset(...)` in a
  one-time setup script under `scripts/`, then referenced by name in CI/local
  eval runs (never recreated on every run).
- **Experiment naming:** `<dataset-name>-<git-short-sha>` so every eval run
  is traceable back to the exact commit that produced it — mirrors the
  existing `traced_agent` convention of tagging every run with
  `[agent_name, company_name]` (`tracing.py`).
- **Evaluator registration:** each build task adds evaluator functions under
  `backend/evals/<agent>_evaluators.py` (new top-level package, sibling to
  `backend/agents/`), each a plain function following LangSmith's
  `(run, example) -> dict` evaluator signature, imported and passed to
  `langsmith.evaluate(...)` from a corresponding
  `scripts/run_eval_<agent>.py` entrypoint.
- **Never raises, same as agents.** Every evaluator function must itself
  follow the codebase's existing "never raise" contract — an evaluator that
  throws on a malformed run should score `0`/`fail` with a caught error
  message in its result dict, not crash the whole experiment (consistent
  with `output_models.py`'s and `tracing.py`'s existing conventions).
- **CI scope.** These are LangSmith-backed evals against a real LLM — they
  are **not** part of the standard `pytest`/CI gate (same reasoning as
  T-106's manual QA script: non-deterministic, costs real API calls, needs a
  live `LANGSMITH_API_KEY`). T-068–T-071 each land as a manually-run script
  plus a pytest unit test that checks the *evaluator function's grading
  logic itself* against synthetic mock runs (deterministic, mocked, safe for
  CI) — the same split already used for `test_tracing.py` mocking
  `configure_tracing()` rather than hitting real LangSmith in CI.

## 5. Grading scale summary

| Eval | Unit graded | Scale | Target |
| --- | --- | --- | --- |
| Fundamental accuracy | Per company (5) | Binary pass/fail → accuracy % | >70% |
| Sentiment direction | Per news set (10) | Binary pass/fail → accuracy % | >80% |
| Sentiment red-flag detection | Per scandal case (3) | Binary pass/fail → count | 3/3 |
| Debate quality | Per pipeline run (3–5) | All-or-nothing per run | Contrarian always disagrees; no repetition; PM engages |
| Memo completeness | Per pipeline run (3–5) | All-or-nothing per run | Every section populated |
| Latency | Per pipeline run (3 companies × N) | p50/p95 numeric | p50 <90s, p95 <120s |

## 6. Naming and sequencing note

For the developer's own tracking, not part of the acceptance criteria: two
different documents will now exist with overlapping "evaluation" naming by
the end of Phase 11 —

- `docs/EVALUATION.md` (existing, Phase 8) — verdict accuracy *in
  production*, scored against real market outcomes after the fact.
- `docs/EVAL_FRAMEWORK_DESIGN.md` (this document, Phase 11) — agent quality
  *before release*, scored against hand-authored ground truth via LangSmith.

When T-072 ("Write `EVALUATION.md`") is picked up, decide there — not here —
whether to keep both files cross-linked (recommended: each file's intro
already gets a one-line pointer to the other) or to merge Phase 8 content
into a new top-level section of a restructured `EVALUATION.md`. This design
doc does not overwrite the Phase 8 file, so both remain intact either way.

**Resolved in T-072:** kept both files separate and intact — `docs/
EVALUATION.md` (Phase 8) is untouched apart from a one-line cross-link
added to its intro. The Phase 11 write-up this doc feeds into lives at
`docs/AGENT_EVALUATION.md` (not a bare `docs/EVALUATION.md` overwrite),
so the acceptance criterion's "EVALUATION.md" is satisfied in spirit — a
complete, recruiter-readable evaluation write-up exists — without
destroying the already-shipped Phase 8 documentation the literal filename
would have collided with. Both files now cross-link to each other and
`docs/AGENT_EVALUATION.md` §9 explains how the two systems relate.

## 7. Open questions for T-068–T-071

Flagged here rather than silently decided, since each affects how much extra
scope its build task carries:

1. **Ground-truth authoring.** The 5 fundamental-accuracy companies and the
   13 sentiment news sets need to be hand-picked and pinned as fixtures
   before T-068/T-069 can run. This is dataset-authoring work, not agent
   code — worth scoping as the first sub-step of each build task rather than
   assuming it's free.
2. **Debate-quality dataset reuse.** §3.3/§3.4 propose reusing
   `test_graph_integration.py`-style fixtures rather than new hand-authored
   ones. Confirm at T-070 time that those fixtures produce a rich-enough
   debate transcript (multiple debate rounds, non-trivial Contrarian output)
   to be a meaningful eval input, not just a schema-shape smoke test.
3. **Novelty-check threshold.** §3.3's "no near-duplicate `counter_arguments`"
   check needs a concrete similarity threshold (token-overlap ratio, or a
   `sentence-transformers` cosine-similarity cutoff — the latter is already
   a project dependency, T-017/ChromaDB). Pick and document the exact
   number in T-070's own PR, not here, since it will need empirical tuning
   against real Contrarian output.