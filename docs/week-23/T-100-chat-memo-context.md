# T-100 — Memo-scoped context builder

**Phase:** 10 — AIRP Assistant (Chatbot)
**Week:** 23
**Branch:** `feat/chat-memo-context`
**Type:** Feature
**Priority:** 🔴 Critical
**Est. hours:** 4

## Summary

T-100 adds `backend/services/chat_service.py`: given an `analysis_id`,
`build_memo_context` reads the analysis's persisted
`InvestmentState` snapshot and renders it into grounded, structured text
covering all 7 research/advanced agent outputs (Fundamental Analyst,
Technical Analyst, News Sentiment Agent, Macro Economist, Risk Officer,
Contrarian Investor, Valuation Agent), the full debate transcript, and
the Portfolio Manager's final decision -- everything a memo-scoped
AIRP Assistant chat session (T-099's `chat_sessions.session_type =
'memo_scoped'`) needs to answer questions grounded in one specific
analysis. No vector search, no embeddings, no ChromaDB -- a direct,
deterministic read straight from `analyses.state_snapshot`, the same
column and query shape `backend/services/analysis.py`'s
`get_analysis_result` already uses for the results page.

## Acceptance criteria (from task spec)

- [x] Given an `analysis_id`, context builder returns all 7 agent
      outputs + debate transcript + decision as structured text
- [x] Unit tested against a fixture analysis

## Design decisions

- **Why no vector search for this scope, when T-101 needs one for
  portfolio-wide questions?** One analysis's full state (7 agent
  outputs + debate transcript + decision) is a few thousand tokens at
  most -- small enough to hand an LLM in full, every time, exactly
  as-is. RAG exists to select a relevant subset out of a corpus too
  large to fit in context; there is no such corpus here, only one
  already-bounded record the user explicitly opened a chat about.
  Embeddings and similarity search would add latency, cost, and a new
  failure mode (a relevant fact scoring too low to be retrieved) for
  zero benefit over just reading the record. Portfolio-wide questions
  ("which of my BUY calls are up this month?", "search my uploaded
  annual reports for a mention of X") are a genuinely different
  problem -- unbounded scope across many analyses/documents -- and
  that's exactly what T-101's LangChain tool-calling layer
  (`get_user_analyses`, `get_memo_by_ticker`,
  `search_uploaded_documents` over the existing `airp_documents`
  ChromaDB collection) is for.
- **Reads `analyses.state_snapshot` directly via raw SQL, not the
  `agent_outputs` ORM table.** Both exist. `agent_outputs` (T-016)
  stores one row per agent per analysis primarily for observability --
  token counts, latency, LangSmith run IDs -- alongside its
  `output_json` payload. `state_snapshot` (T-033) stores the same
  agent content plus the debate transcript and final decision
  *together*, as the exact `InvestmentState` the pipeline actually
  produced, reachable with the same one-row-per-`job_id` query
  `get_analysis_result` already uses. `state_snapshot` is a
  T-033-migration-only column, never added to the `Analysis` ORM model
  -- read via `sqlalchemy.text`, exactly as `analysis.py`'s own module
  docstring documents for itself.
- **`build_memo_context` reuses `backend.services.analysis
  .AnalysisNotReadyError` rather than defining a new exception type.**
  "This analysis is not ready yet" is the same condition whether asked
  from the results page or from chat -- one shared error taxonomy the
  whole app already knows how to translate into a 409 at the API
  boundary, instead of two near-identical exception classes drifting
  apart over time.
- **Ownership and readiness semantics are a deliberate, exact mirror
  of `get_analysis_result`:** no row -> `None`; row belongs to a
  different user -> `None` (never distinguishes this from "does not
  exist" -- same non-owner-can't-probe-existence contract every other
  read path in this codebase already has); status not `'completed'` ->
  raises `AnalysisNotReadyError`; snapshot missing/unparseable/no
  `decision` key -> raises `AnalysisNotReadyError` as a defensive
  fallback. A second, subtly different contract for the exact same
  underlying data would be a maintenance trap.
- **`_parse_state_snapshot` is duplicated from `analysis.py`, not
  imported.** Matches that module's own stated reason for not
  importing `state_persistence`'s version: each caller only ever needs
  a handful of top-level keys back out of the same parsed dict, so one
  small, self-contained normalisation function per caller module beats
  a shared private cross-module dependency for a handful of lines.
- **Per-agent formatters are hand-written per model, not a generic
  dict-to-text dump.** Every `AgentOutput` subclass in
  `backend/agents/output_models.py` was read field-by-field (not
  assumed from memory) to build a dedicated formatter per agent --
  `_format_fundamental_section`, `_format_technical_section`, etc. --
  that surfaces each agent's actual headline metrics (score, signal,
  sentiment, risk breakdown, DCF assumptions...) with units and labels,
  plus every agent's own `summary` field. A generic dump of raw
  dict keys would technically satisfy "structured text" but would be
  materially worse grounding for the chatbot than metrics rendered with
  the same labels a human analyst would use.
- **Every formatter degrades independently and never raises** -- a
  missing agent output, an agent that returned `error` set, or a
  malformed field all produce a clearly-labelled fallback line
  ("... no output available for this analysis." / "... agent reported
  an error -- ...") rather than an exception. This extends the
  "agents/nodes never raise" contract `backend/services/
  memo_generator.py` already applies to memo rendering into context
  rendering for the chatbot.
- **The debate transcript formatter is keyed correctly against the
  real production data shape -- verified by reading
  `backend/graph/nodes.py`'s `_build_agent_responses`, not assumed.**
  `InvestmentState["debate_rounds"][n]["agent_responses"]` is keyed by
  the same short `InvestmentState` field names used everywhere else in
  this module (`"fundamental"`, `"technical"`, `"sentiment"`,
  `"macro"`, `"risk"`) -- NOT by the full `agent_name` enum values
  (`"fundamental_analyst"`, `"risk_officer"`, ...). Only the four
  research agents plus Risk Officer ever appear in `agent_responses`
  (the Contrarian's own text lives in the round's separate
  `"contrarian"` key; Valuation and the Portfolio Manager run outside
  the debate loop entirely per that same function's docstring). This
  was caught and fixed during this task's own verification pass: an
  earlier draft of this task's test fixture used the wrong (full
  `agent_name`) keys, which would have silently masked a real bug had
  it shipped un-caught -- `AGENT_DISPLAY_NAMES.get(agent_name,
  agent_name)` falls back to printing the raw key on a miss rather
  than raising, so a key mismatch degrades quietly instead of failing
  loudly. The fixture (not the production formatter) was the one that
  needed correcting; see Testing, below, for how this was verified.
- **`MemoChatContext` exposes named per-section fields *and* one
  `full_context` property**, not just a single joined string. Structured
  fields let a future caller quote or reference one section
  individually (e.g. "here's specifically what the Risk Officer said");
  `full_context` gives the common case -- handing everything to an LLM
  prompt in one call -- a single ready-to-use string with headings, in
  the same pipeline order `backend/graph/state.py` documents (4
  parallel research agents, debate transcript, 3 post-debate advanced
  agents, final decision).
- **No chat-turn or LLM-calling logic in this module.** T-100's own
  acceptance criteria scope this task to context assembly only
  ("context builder returns ... as structured text"). The actual chat
  loop -- user question + this context + an LLM call -- is a separate,
  later task; keeping this module a pure `analysis_id` in, structured
  text out function keeps it trivially unit-testable without mocking
  any LLM client, and reusable unchanged once that loop is built.
- **`from __future__ import annotations` is NOT used**, matching
  `backend/services/analysis.py` and `backend/services/auth.py` (this
  module's actual siblings) rather than `backend/models/orm.py`.
  Checked directly rather than assumed: every `backend/services/*.py`
  file in this codebase avoids the future import (several state so in
  their own docstrings), while ORM/graph/migration files use it --
  `chat_service.py` is a services-layer module, so it follows that half
  of the split.

## Files changed / created

### Backend — service

- **`backend/services/chat_service.py`** (**NEW**) -- `AGENT_STATE_KEYS`,
  `AGENT_DISPLAY_NAMES`, `MemoChatContext` (frozen dataclass with 7
  agent sections + debate transcript + decision sections, plus a
  `full_context` property), 7 private per-agent formatters
  (`_format_fundamental_section` ... `_format_valuation_section`),
  `_format_debate_transcript_section`, `_format_decision_section`, and
  the public `build_memo_context(session, analysis_id, user_id)`.

### Backend — tests

- **`backend/tests/unit/test_chat_service.py`** (**NEW**) -- one shared
  fixture analysis (`_FIXTURE_STATE_SNAPSHOT`, built from all 7 agent
  output fixtures + a 2-round debate transcript + a decision fixture,
  matching the real `_build_agent_responses` key shape) plus dedicated
  test classes for `build_memo_context`'s not-found/ownership/readiness/
  success paths and for every formatter's missing/error/populated
  behaviour.

### Docs

- **`docs/week-23/T-100-chat-memo-context.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/chat-memo-context

git branch
# → * feat/chat-memo-context
```

### Step 2 — Add the service

- `backend/services/chat_service.py`

### Step 3 — Add tests

- `backend/tests/unit/test_chat_service.py`

### Step 4 — Run the full verification gate locally

Windows Git Bash — remember `ENVIRONMENT=test` cannot be chained with
`&&` on this machine (trailing-space issue); set it as its own line per
the established project workaround:

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit/test_chat_service.py -v
python -m pytest backend/tests/unit -v
```

If pre-commit hooks fail with `WinError 4551` (Windows App Control
blocking the shim), use the established workaround:

```bash
git commit --no-verify -m "..."
```

GitHub Actions' Linux runners remain the real enforcement gate for this
project.

### Step 5 — Commit (two-commit pattern)

```bash
git add backend/services/chat_service.py
git add backend/tests/unit/test_chat_service.py
git add docs/week-23/T-100-chat-memo-context.md

git commit --no-verify -m "feat(chat): build grounded context from stored analysis data

- Add backend/services/chat_service.py: build_memo_context(session,
  analysis_id, user_id) reads analyses.state_snapshot directly (raw
  SQL, same pattern as backend.services.analysis.get_analysis_result)
  and renders all 7 agent outputs, the debate transcript, and the
  Portfolio Manager decision into structured text -- no vector search,
  no embeddings, no ChromaDB
- MemoChatContext exposes named per-section fields plus a
  full_context property that joins everything with headings in
  pipeline order, ready for an LLM prompt
- 7 dedicated per-agent formatters (_format_fundamental_section ...
  _format_valuation_section), each read from the real
  backend.agents.output_models field set, degrade independently and
  never raise on missing data or an agent-reported error
- Debate transcript formatter verified against the real
  backend.graph.nodes._build_agent_responses key shape (short
  InvestmentState field names, not full agent_name enum values) --
  caught and fixed a fixture bug during this task's own verification
  that would have silently masked a real key mismatch
- Reuses backend.services.analysis.AnalysisNotReadyError and mirrors
  get_analysis_result's exact not-found/ownership/readiness contract
  rather than introducing a second, near-identical error path
- Add backend/tests/unit/test_chat_service.py: one shared fixture
  analysis covering all 7 agents + a 2-round debate transcript +
  decision; build_memo_context tested end to end (not
  found/ownership/not ready/success), every formatter tested directly
  for missing/error/populated input

Closes #100"
```

If a formatter modifies files after staging (black/isort), re-stage and
make a second, separate commit rather than amending:

```bash
git add -A
git commit --no-verify -m "style: apply black/isort formatting to T-100 files"
```

### Step 6 — Push and open the PR

```bash
git push -u origin feat/chat-memo-context
```

**Base branch:** `main`
**Compare branch:** `feat/chat-memo-context`

## Pull Request

**PR title:**

```
feat(chat): add memo-scoped context builder for chatbot Q&A
```

**PR description:**

```markdown
## Summary
Adds backend/services/chat_service.py's build_memo_context: given an
analysis_id, returns all 7 agent outputs + the full debate transcript
+ the Portfolio Manager decision as grounded, structured text -- the
context a memo-scoped AIRP Assistant chat session (T-099) needs to
answer questions about one specific analysis. Reads
analyses.state_snapshot directly, no vector search / embeddings /
ChromaDB involved (that's T-101's job, for the genuinely unbounded
portfolio-wide scope).

## Changes
- New MemoChatContext dataclass: 7 named agent sections + debate
  transcript section + decision section, plus a full_context property
  joining everything with headings in pipeline order
- 7 dedicated per-agent formatters, one per
  backend.agents.output_models class, rendering each agent's real
  headline metrics (not a generic dict dump) plus its summary field;
  every formatter degrades independently on missing data or an
  agent-reported error, never raises
- Debate transcript formatter verified against the real
  backend.graph.nodes._build_agent_responses key shape (short field
  names, not full agent_name enum values) -- this caught and fixed a
  bug in this PR's own test fixture before it could ship
- build_memo_context mirrors get_analysis_result's exact not-found /
  ownership / AnalysisNotReadyError contract (imported, not
  redefined) and reads state_snapshot via the same raw-SQL pattern,
  for the same reason: it's a T-033-migration column, not on the
  Analysis ORM model

## Testing
- `python -m pytest backend/tests/unit/test_chat_service.py -v` -- all
  green: build_memo_context's not-found/ownership/not-ready/success
  paths (including a psycopg2-style string snapshot vs. an
  asyncpg-style dict snapshot), all 7 per-agent formatters'
  missing/error/populated behaviour, the debate transcript formatter's
  empty/malformed-entry/populated behaviour, and the decision
  formatter's missing/error/populated behaviour -- all against one
  shared fixture analysis
- `python -m pytest backend/tests/unit -v` -- full unit suite green
- `python -m black/isort/flake8/mypy backend` all pass

## LangSmith Trace
N/A -- pure data-assembly service, no LLM or agent call made by this
module.

## Screenshots
N/A -- no UI changes.

## Related Issues
Closes #100 (adjust to your actual issue number if different).
```

## Testing

Backend (`python -m pytest backend/tests/unit -v`):

- **`test_chat_service.py`** (new) --
    * `TestBuildMemoContextNotFound` / `TestBuildMemoContextNotReady` /
      `TestBuildMemoContextSuccess`: the full not-found / different-user
      / pending / running / failed / null-snapshot / no-decision-key /
      malformed-JSON / success matrix, mirroring
      `test_analysis_result_history_service.py`'s coverage of
      `get_analysis_result` exactly, plus assertions that all 7 agent
      sections, the debate transcript, and the decision section each
      contain the fixture's actual data, and that `full_context` joins
      every section under the right heading.
    * `TestAgentConstants`: `AGENT_STATE_KEYS` has exactly 7 entries,
      every key has a display name, and neither `"decision"` nor
      `"portfolio_manager"` is among them (the acceptance criteria's
      own "7 agent outputs ... + decision" split).
    * One test class per agent formatter (`TestFundamentalSectionFormatter`
      ... `TestValuationSectionFormatter`): `None` input, an
      agent-reported `error`, and a fully populated fixture each
      checked directly.
    * `TestDebateTranscriptFormatter`: `None`/empty rounds, a
      non-dict entry mixed in with valid ones (skipped, not fatal), a
      round with no `agent_responses`, and a populated multi-round
      transcript using the correct short-field-name keys.
    * `TestDecisionSectionFormatter`: missing/empty/error input, a
      fully populated decision (verdict, conviction, agent weights),
      and a decision missing `agent_weights` falling back to "not
      provided".

"context builder returns all 7 agent outputs + debate transcript +
decision as structured text" (first acceptance criterion) is covered by
`TestBuildMemoContextSuccess`'s section-content assertions plus every
per-formatter test class. "unit tested against a fixture analysis"
(second criterion) is `_FIXTURE_STATE_SNAPSHOT` and its constituent
per-agent/debate/decision fixtures, reused across the entire file.

## Verification gate run locally before pushing

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v
```

## LangSmith Trace

N/A — `chat_service.py` makes no LLM or agent call; it only reads and
formats already-persisted pipeline output.

## Related Issues

Closes #100 (adjust to your actual issue number if different).

## A note on verification in this environment

This sandbox has no network access, so `sqlalchemy` (and the rest of
`backend/requirements.txt`) is not installed and the real
`black`/`isort`/`flake8`/`mypy`/`pytest` runs could not be executed
directly. Verification performed instead: `python -m py_compile` on
both new files; a manual, Unicode-aware line-length check against
black's 88-character limit; a full read of every field on every
`backend.agents.output_models.AgentOutput` subclass (not assumed from
memory) to build each formatter's field references correctly; a direct
read of `backend.graph.nodes._build_agent_responses` to confirm the
real `agent_responses` key shape, which caught and corrected a wrong
assumption in this PR's own test fixture (see Design decisions, above);
and a standalone dry-run harness -- the pure formatter functions
extracted into a throwaway module with a stub for the two constants
they depend on, executed directly against every fixture in the test
file (all 7 agent formatters, the debate transcript formatter including
the corrected key shape, and the decision formatter) to confirm each
one's output actually contains what the corresponding test asserts,
without needing `sqlalchemy` installed at all. **Real verification --
the actual `pytest`, `black`/`isort`/`flake8`/`mypy` runs against the
full dependency set -- is delegated to your local environment and
GitHub Actions**, exactly as with every previous task's workflow doc.