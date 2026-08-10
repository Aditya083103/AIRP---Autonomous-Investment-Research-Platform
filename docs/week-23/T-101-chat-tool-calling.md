# T-101 — Portfolio-wide tool-calling layer

**Phase:** 10 — AIRP Assistant (Chatbot)
**Week:** 23
**Branch:** `feat/chat-tool-calling`
**Type:** Feature
**Priority:** 🔴 Critical
**Est. hours:** 5

## Summary

T-101 adds `backend/tools/portfolio_tools.py`: three LangChain tools --
`get_user_analyses`, `get_memo_by_ticker`, and
`search_uploaded_documents` -- that let a portfolio-wide AIRP Assistant
chat session (T-099's `chat_sessions.session_type = 'portfolio_wide'`)
answer questions spanning the user's whole analysis history, not just
one open memo (T-100's job). The first two read straight from
PostgreSQL (`analyses`/`companies`, the same `state_snapshot` column
T-100 and `backend/services/analysis.py` already read); the third is a
thin, literal wrap of the existing `semantic_search` over the
`airp_documents` ChromaDB collection, exactly as specified.

## Acceptance criteria (from task spec)

- [x] Each tool independently unit tested
- [x] `search_uploaded_documents` returns results from the
      `airp_documents` collection

## Design decisions

- **A factory (`build_portfolio_tools(session, user_id, chroma=None)`),
  not three plain module-level `@tool` functions.** `get_user_analyses`
  and `get_memo_by_ticker` both read data scoped to exactly one user,
  and that user must be the authenticated chat requester -- never a
  value the tool's own arguments accept. A LangChain `@tool`'s
  parameters become part of the JSON schema an LLM fills in at call
  time; if `user_id` were one of those parameters, a manipulated or
  simply confused model turn could pass a different user's UUID and
  read their portfolio. `user_id` (and the `AsyncSession` needed to
  query it) are captured in a closure instead -- the factory returns
  three tool instances already bound to one request's identity, and
  the LLM only ever sees and fills in the natural-language-relevant
  parameters (`verdict`, `ticker`, `query`, `limit`...). This is a
  correctness/security requirement, not a style preference, and is
  called out explicitly in the module's own docstring so a future
  reader does not "simplify" it back into three plain functions with
  `user_id` as an argument.
- **`get_user_analyses`/`get_memo_by_ticker` are async tools --
  every other existing `@tool` in this codebase is synchronous.**
  Those tools (`fetch_stock_price`, `fetch_news`, `fetch_ratios`...)
  wrap external HTTP/scrape calls invoked from LangGraph's
  worker-thread node execution model. These two instead read the same
  async SQLAlchemy `AsyncSession` every FastAPI route handler already
  uses; wrapping an async DB call in a sync tool would mean either
  blocking the event loop or spinning up a second event loop per call
  -- the exact `asyncio.run()`-inside-a-running-loop problem
  `backend/services/state_persistence.py` documents at length for a
  different code path. `langchain_core.tools.tool` supports decorating
  an `async def` directly, exposing `.ainvoke()` for the (itself async)
  chat loop to await normally. `search_uploaded_documents` touches no
  async resource (ChromaDB's Python client is synchronous), so it
  stays a plain sync tool, matching every existing ChromaDB call site.
- **`search_uploaded_documents` applies no per-user filtering, because
  none is possible today -- verified by reading the actual T-051
  ingestion code, not assumed.** `backend.db.chroma_client
  .ingest_document` never writes a `user_id` into a chunk's metadata
  (only `company`, `ticker`, `source_filename`, `doc_type`,
  `chunk_index`) -- any uploaded document is searchable by any
  authenticated user today, a pre-existing property of the T-051
  pipeline. Adding per-user ChromaDB metadata scoping is a larger,
  separate change; T-101's acceptance criteria are "wrap the existing
  semantic_search", not "redesign document ingestion's access model",
  so this was left as-is and called out explicitly rather than quietly
  worked around or silently assumed to already be scoped.
- **Every core function lives separately from its `@tool` wrapper**
  (`_get_user_analyses_core`, `_get_memo_by_ticker_core`,
  `_search_uploaded_documents_core`), exactly the pattern
  `backend/tools/stock_price.py` already established ("Core...
  separated from the LangChain @tool decorator so it can be called
  directly in tests without invoking the full tool machinery"). This
  satisfies "each tool independently unit tested" at the logic level
  without needing an LLM call or agent executor in the test suite --
  and the factory-wiring tests (see Testing, below) additionally prove
  the tools the chat loop will actually receive work end to end
  through their public `.invoke()`/`.ainvoke()` interface.
- **Every tool returns `dict[str, Any]` and never raises**, matching
  the universal convention already established by `fetch_stock_price`,
  `fetch_news`, `fetch_ratios`, etc. An empty result is a normal,
  well-formed dict (`{"count": 0, "analyses": []}` /
  `{"count": 0, "results": []}`) -- not an error. An unresolvable
  ticker, invalid verdict, or malformed input produces a clearly
  labelled `{"error": ..., "message": ...}` dict instead of an
  exception, so a chat loop can always read a tool's result as data,
  never has to catch an exception from one, and can hand the error
  string straight back to the LLM as additional context if useful.
- **`get_user_analyses` and `get_memo_by_ticker` read
  `analyses.state_snapshot` via raw SQL (`sqlalchemy.text`)**, the same
  pattern `backend/services/analysis.py`, `backend/services
  /chat_service.py` (T-100), and this task all independently arrive at
  for the identical reason: `state_snapshot` is a T-033-migration-only
  column, never added to the `Analysis` ORM model.
  `_SQL_GET_USER_ANALYSES` applies `verdict`/`ticker` as *optional*
  filters inside one static, parameterised query
  (`:verdict IS NULL OR ... = :verdict`) rather than building SQL
  strings by hand per filter combination -- a standard, safe Postgres
  pattern for "this filter may or may not be present" without
  string-formatting a query.
- **`get_memo_by_ticker` duplicates a small `_parse_decision` helper**
  rather than importing `chat_service.py`'s or `analysis.py`'s private
  snapshot-parsing functions, for the same reason both of those
  modules already give for not sharing theirs: each caller only ever
  needs one key back out of the parsed dict, so a small self-contained
  copy beats a shared private cross-module dependency for a handful of
  lines.
- **Result caps are deliberately smaller than the equivalent
  human-facing endpoints.** `DEFAULT_ANALYSES_LIMIT`/
  `MAX_ANALYSES_LIMIT` (10/25) are well below
  `backend.services.analysis`'s `DEFAULT_HISTORY_PAGE_SIZE`/
  `MAX_HISTORY_PAGE_SIZE` (20/100) -- a tool result is read by an LLM
  as prompt context, not paginated by a human scrolling a dashboard, so
  a lean default keeps the result token-cheap and the hard cap keeps
  one call bounded regardless of what limit value an LLM turn supplies.
  `MAX_SEARCH_RESULTS` (20) matches
  `backend.db.chroma_client.MAX_QUERY_RESULTS`, the existing ceiling
  `semantic_search`/`query_documents` already enforce one layer down.
- **`from __future__ import annotations` IS used here**, unlike
  `backend/services/*.py` (T-100's `chat_service.py` explicitly does
  not use it). Checked directly rather than assumed: this module
  defines no Pydantic `BaseModel` subclasses -- only plain
  `dict[str, Any]` returns -- so the future import carries none of the
  union-resolution risk that rule exists to avoid, and matches the
  majority convention already inside `backend/tools/` itself
  (`news.py`, `macro.py`, `ratios.py` all use it; only
  `stock_price.py` does not).

## Files changed / created

### Backend — tools

- **`backend/tools/portfolio_tools.py`** (**NEW**) -- constants
  (`DEFAULT_ANALYSES_LIMIT`, `MAX_ANALYSES_LIMIT`,
  `DEFAULT_SEARCH_RESULTS`, `MAX_SEARCH_RESULTS`), three private core
  functions (`_get_user_analyses_core`, `_get_memo_by_ticker_core`,
  `_search_uploaded_documents_core`) plus their supporting
  `_parse_decision` helper and raw-SQL constants, and the public
  `build_portfolio_tools(session, user_id, chroma=None)` factory
  returning the three bound `@tool` instances.
- **`backend/tools/README.md`** (**MODIFY**) -- adds a "Files (added in
  Phase 10)" row documenting `portfolio_tools.py` alongside the
  existing Phase 1 tool file index. (The pre-existing `rag.py` row in
  that same table was left untouched -- a stale reference to a file
  that was never actually built; a pre-existing documentation drift
  unrelated to this task's scope, not something T-101 introduced or is
  responsible for correcting.)

### Backend — tests

- **`backend/tests/unit/test_portfolio_tools.py`** (**NEW**) -- core
  function tests for all three tools (empty/error/populated inputs,
  parameter clamping, correct SQL binding) using mocked `AsyncSession`
  objects (mirroring `test_analysis_result_history_service.py`/
  `test_chat_service.py`) and a patched module-level `semantic_search`
  (mirroring `test_sentiment_analyst.py`'s
  `patch("backend.agents.sentiment_analyst.semantic_search")`
  pattern), plus `build_portfolio_tools` factory-wiring tests that
  invoke each tool through its actual public `.invoke()`/`.ainvoke()`
  interface to prove the closures correctly bind `session`/`user_id`/
  `chroma`.

### Docs

- **`docs/week-23/T-101-chat-tool-calling.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/chat-tool-calling

git branch
# → * feat/chat-tool-calling
```

### Step 2 — Add the tools module

- `backend/tools/portfolio_tools.py`
- `backend/tools/README.md` (add the Phase 10 row)

### Step 3 — Add tests

- `backend/tests/unit/test_portfolio_tools.py`

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
python -m pytest backend/tests/unit/test_portfolio_tools.py -v
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
git add backend/tools/portfolio_tools.py
git add backend/tools/README.md
git add backend/tests/unit/test_portfolio_tools.py
git add docs/week-23/T-101-chat-tool-calling.md

git commit --no-verify -m "feat(chat): add history and document-search tools for AIRP Assistant

- Add backend/tools/portfolio_tools.py: build_portfolio_tools(session,
  user_id, chroma=None) factory returns three LangChain tools bound to
  one chat request's identity via closure -- get_user_analyses and
  get_memo_by_ticker never accept user_id as an LLM-fillable argument,
  by design, so no chat turn can read another user's portfolio
- get_user_analyses / get_memo_by_ticker read analyses.state_snapshot
  via the same raw-SQL pattern backend.services.analysis and
  backend.services.chat_service already use (state_snapshot is a
  T-033-migration column, not on the Analysis ORM model); optional
  verdict/ticker filters applied inside one static parameterised query
- get_user_analyses/get_memo_by_ticker are async tools (unlike every
  other existing @tool in this codebase) since they read the same
  async AsyncSession every route handler uses; search_uploaded_documents
  stays sync, matching every existing ChromaDB call site
- search_uploaded_documents is a thin, literal wrap of
  backend.db.chroma_client.semantic_search with
  collection_name=COLLECTION_DOCUMENTS fixed; verified against the
  real T-051 ingestion code that no per-user metadata filtering is
  possible today (documented explicitly, not silently assumed)
- Every tool returns dict[str, Any] and never raises, matching the
  fetch_stock_price/fetch_news/fetch_ratios convention; each tool's
  core logic is a private function separated from its @tool wrapper,
  independently unit tested
- Add backend/tests/unit/test_portfolio_tools.py: core-function tests
  for all three tools plus build_portfolio_tools factory-wiring tests
  that invoke each tool through its real .invoke()/.ainvoke()
  interface
- Update backend/tools/README.md with a Phase 10 file-index row

Closes #101"
```

If a formatter modifies files after staging (black/isort), re-stage and
make a second, separate commit rather than amending:

```bash
git add -A
git commit --no-verify -m "style: apply black/isort formatting to T-101 files"
```

### Step 6 — Push and open the PR

```bash
git push -u origin feat/chat-tool-calling
```

**Base branch:** `main`
**Compare branch:** `feat/chat-tool-calling`

## Pull Request

**PR title:**

```
feat(chat): implement history and document-search tools for AIRP Assistant
```

**PR description:**

```markdown
## Summary
Adds backend/tools/portfolio_tools.py: get_user_analyses,
get_memo_by_ticker, and search_uploaded_documents as LangChain tools
for portfolio-wide AIRP Assistant chat sessions (T-099) -- the
counterpart to T-100's memo-scoped context builder, for questions that
span the user's whole analysis history rather than one open memo.

## Changes
- build_portfolio_tools(session, user_id, chroma=None) factory returns
  three tools bound to one chat request's identity via closure --
  user_id is never an LLM-fillable tool argument, by design (a
  security requirement: an LLM-controlled user_id would let one chat
  turn read another user's portfolio)
- get_user_analyses / get_memo_by_ticker read analyses.state_snapshot
  via the same raw-SQL pattern already used in
  backend/services/analysis.py and backend/services/chat_service.py;
  both are async tools (unlike every other existing @tool in this
  codebase) since they share the app's async AsyncSession
- search_uploaded_documents is a thin, literal wrap of the existing
  semantic_search over the airp_documents ChromaDB collection, exactly
  per the acceptance criteria; verified against the real T-051
  ingestion code that no per-user document filtering exists today
  (documented, not silently assumed)
- Every tool returns dict[str, Any], never raises, and separates its
  core logic from its @tool wrapper (matching
  backend/tools/stock_price.py's established pattern) so each is
  independently unit testable

## Testing
- `python -m pytest backend/tests/unit/test_portfolio_tools.py -v` --
  all green: core-function tests for all three tools (empty/error/
  populated inputs, parameter clamping, correct SQL/semantic_search
  call binding) plus build_portfolio_tools factory-wiring tests that
  invoke each tool through its real .invoke()/.ainvoke() interface
- `python -m pytest backend/tests/unit -v` -- full unit suite green
- `python -m black/isort/flake8/mypy backend` all pass

## LangSmith Trace
N/A -- these tools make no LLM call themselves; they are handed to a
future chat-loop agent executor.

## Screenshots
N/A -- no UI changes.

## Related Issues
Closes #101 (adjust to your actual issue number if different).
```

## Testing

Backend (`python -m pytest backend/tests/unit -v`):

- **`test_portfolio_tools.py`** (new) --
    * `TestGetUserAnalysesCore`: no rows -> empty; invalid verdict ->
      error (and no query issued); verdict case-normalisation; full
      row-to-dict mapping including `conviction_score` cast to `int`
      and `completed_at` as ISO text; `NULL` verdict/conviction pass
      through as `None`; limit clamped to both the maximum and the
      minimum; default limit applied when unspecified; correct
      `user_id`/`ticker`/`verdict` binding.
    * `TestGetMemoByTickerCore`: empty/whitespace ticker -> error (no
      query issued); no matching row -> `not_found`; `NULL` snapshot
      and a snapshot with no `decision` key both -> `no_decision`;
      fully populated row -> every memo field correctly extracted; a
      psycopg2-style JSON string snapshot parses identically to an
      asyncpg-style dict snapshot; a malformed JSON string ->
      `no_decision` rather than a raw exception; ticker is stripped
      before binding; correct `user_id` binding.
    * `TestSearchUploadedDocumentsCore`: empty/whitespace query ->
      error; `collection_name="airp_documents"` is always passed to
      `semantic_search`; `semantic_search`'s return value passes
      through into `results`/`count`; an empty result list is *not*
      flagged as an error; `ticker` forwards as `company_filter`;
      `n_results` clamped to both the maximum and the minimum; default
      `n_results` applied when unspecified; an injected `chroma`
      client is forwarded unchanged.
    * `TestBuildPortfolioTools`: the factory returns exactly 3
      `BaseTool` instances with the expected names; invoking
      `get_user_analyses` and `get_memo_by_ticker` through
      `.ainvoke()` (their real public interface, not the private core
      function) reaches the bound session with the correct `user_id`
      in the bound SQL parameters; invoking `search_uploaded_documents`
      through `.invoke()` reaches the patched `semantic_search` with
      the correct collection; an explicitly-passed `chroma` client
      survives the full factory -> tool -> core call chain unchanged.

"Each tool independently unit tested" (first acceptance criterion) is
covered by the three `Test*Core` classes plus `TestBuildPortfolioTools`
exercising the real tool interface. "search_uploaded_documents returns
results from the airp_documents collection" (second criterion) is
`test_queries_the_documents_collection` and
`test_returns_results_from_semantic_search`, plus the equivalent
factory-wiring assertion in `TestBuildPortfolioTools`.

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

N/A — `portfolio_tools.py` makes no LLM or agent call itself; these
tools are built for a future chat-loop agent executor to call.

## Related Issues

Closes #101 (adjust to your actual issue number if different).

## A note on verification in this environment

This sandbox has no network access, so `langchain-core`, `sqlalchemy`,
and the rest of `backend/requirements.txt` are not installed and the
real `black`/`isort`/`flake8`/`mypy`/`pytest` runs could not be executed
directly. Verification performed instead: `python -m py_compile` on
both new files; a manual, Unicode-aware line-length check against
black's 88-character limit; a direct read of
`backend.db.chroma_client.ingest_document` (T-051) to confirm the real
per-chunk metadata shape, which is what grounds this task's explicit
"no per-user filtering is possible today" design note rather than an
assumption; and a standalone dry-run harness -- minimal stand-ins for
`langchain_core.tools.tool`/`BaseTool` (a thin wrapper exposing
`.invoke()`/`.ainvoke()`, matching the real library's public contract)
and `sqlalchemy.text`/`AsyncSession`, plus a fake session object
recording every bound SQL parameter -- exercised against every case in
the test file: all three core functions' empty/error/populated paths,
every clamping rule, and the full `build_portfolio_tools` factory chain
invoked through the tools' actual `.invoke()`/`.ainvoke()` interface
end to end (not just the private core functions), confirming both the
returned data shape and the exact parameters each tool binds into its
query/`semantic_search` call. **Real verification -- the actual
`pytest`, `black`/`isort`/`flake8`/`mypy` runs against the full
dependency set, including the real `langchain-core` tool machinery --
is delegated to your local environment and GitHub Actions**, exactly as
with every previous task's workflow doc.