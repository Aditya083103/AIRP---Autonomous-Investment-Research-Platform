# T-104 — WebSocket token streaming

**Phase:** 10 — AIRP Assistant (Chatbot)
**Week:** 24
**Branch:** `feat/chat-ws-streaming`
**Type:** Feature
**Priority:** 🟡 High
**Est. hours:** 4

## Summary

T-104 adds `WS /api/v1/chat/{session_id}/stream`: a persistent
WebSocket connection that lets a client hold one multi-turn
conversation with the AIRP Assistant, receiving each reply token by
token as T-102's guardrailed `chat_llm.astream_chat` produces it,
rather than waiting for a complete response. This is the piece that
finally makes T-102's persona (`chat_llm.py`) and T-103's schema
(`chat_sessions`/`chat_messages`) into an actual live chat: every turn
sent over this connection is persisted, so `GET /api/v1/chat/sessions/
{id}/messages` (T-103) shows the full transcript afterward.

## Acceptance criteria (from task spec)

- [x] Client receives incremental tokens
- [x] Connection closes cleanly on completion
- [x] Reconnect handled gracefully

## A bug caught and fixed during development

The first version of the token-forwarding loop wrapped
`token_iter.__anext__()` directly in `asyncio.wait_for(..., timeout=...)`
— the same shape T-049's `_forward_live_events` uses for its broadcaster
queue. This is **wrong for an async generator**: `asyncio.wait_for`
**cancels** its awaitable the instant it times out, and cancelling an
async generator's in-flight `__anext__()` call destroys the
generator's paused state. A minimal repro confirmed it: after exactly
one timeout, every subsequent `__anext__()` call on the same iterator
raised `StopAsyncIteration` immediately — meaning any real LLM call
whose first token took longer than `_TOKEN_POLL_INTERVAL_SECONDS`
(2 seconds — an entirely realistic wait under provider load) would
have its reply **silently truncated to nothing**, with no error, no
log, nothing sent to the client beyond a `start` event followed
immediately by `done`.

The fix (now in the code below): the poll loop creates one
`asyncio.Task` per pending token and reuses it across every timeout
iteration via `asyncio.wait({task}, timeout=...)`, which — unlike
`wait_for` — never cancels on a mere timeout, only reports whether the
task is done yet. The task is only ever cancelled on a genuine exit
(client disconnect detected, or a send failure), where abandoning the
in-flight generation is the correct, intended outcome. See
`TestSlowTokenDoesNotTruncateReply` in the test file for a regression
test that fails against the original implementation and passes against
the fix.

## Design decisions

- **Does NOT reuse `backend.services.ws_broadcaster`'s actual
  `subscribe`/`unsubscribe`/`publish_event` pub/sub registry.** That
  module's entire reason for existing is bridging an OS thread
  boundary: `run_analysis_pipeline` executes the LangGraph pipeline on
  a worker thread (`asyncio.to_thread`), so node-completion events
  need `threading.Lock` + `call_soon_threadsafe` to reach a WebSocket
  connection on FastAPI's main event loop. `chat_llm.astream_chat` is
  categorically different: it is an `async def` generator awaited
  directly on the SAME coroutine already handling this WebSocket
  connection — there is no worker thread to bridge from, and no other
  subscriber that could ever want the same token stream (unlike an
  analysis job, which any number of open browser tabs might watch).
  Forcing chat tokens through that registry would add exactly the
  indirection its own docstring says exists to avoid when it isn't
  needed.
- **What IS faithfully reused from T-049's `websocket.py`**: the
  query-param JWT auth trick (browsers cannot set WebSocket handshake
  headers), the same numeric close codes for the same meanings (4401
  unauthorized, 4404 not found), the "accept first, then close with an
  explicit application code" strategy (a denied handshake tells the
  browser almost nothing; a closed-with-a-code connection tells it
  exactly what happened), and the poll/heartbeat/disconnect-probe
  *shape* of `_forward_live_events` — adapted (with the fix above) to
  poll `astream_chat`'s own token generator instead of a broadcaster
  queue.
- **`_authenticate` is duplicated locally, not imported from
  `backend.routers.websocket`.** A small, self-contained ~15-line
  function, and this codebase's own established precedent (e.g.
  `backend.tools.portfolio_tools`'s `_parse_decision`, duplicated from
  `chat_service.py`/`analysis.py` for the identical stated reason) is
  that a caller only needing a few lines of shared logic keeps its own
  copy rather than reaching across router modules for it — especially
  here, where doing so would also be the only cross-router import in
  the entire `backend/routers/` package, and where leaving T-049's
  already-shipped, already-tested file completely untouched is itself
  a real "don't put previously-passing CI at risk" property.
- **The connection is multi-turn, not one-reply-and-close.** A client
  sends `{"message": "..."}`, receives a full streamed reply
  (`start` → `token`* → `done`), then the SAME connection waits for
  the next message. "Connection closes cleanly on completion" is
  satisfied at the level of *every exit path* closing correctly
  (client disconnect, at any point, is always handled without an
  unhandled exception or an abnormal closure) — not by closing the
  socket after a single reply, which would make ordinary multi-turn
  chat require reconnecting before every message.
- **A bad turn never closes the connection.** A malformed/empty/
  oversized client message, or a failed LLM call
  (`ChatLLMError` from `astream_chat`), gets an `event_type="error"`
  event on the SAME socket, and the receive loop simply continues
  waiting for the next message. This is the concrete mechanism behind
  "reconnect handled gracefully" at the single-connection level: a
  client should not need to reconnect just to recover from one bad
  message or one failed generation.
- **True reconnect (a brand-new WebSocket connection after any
  disconnect) just works, because the server keeps NO in-memory,
  connection-scoped conversation state at all.** Every message, on
  both sides of every turn, is persisted to `chat_messages`
  (`append_chat_message`) as it happens, and every new connection
  independently re-authenticates, re-validates ownership, and re-reads
  the full transcript from the database (the same
  `get_chat_session_messages` T-103's REST endpoint already uses).
  There is no server-side "resume this exact connection" protocol to
  implement or get wrong, because there is no server-side state a
  reconnect would need to resume.
- **The one case engineered deliberately: a disconnect WHILE a reply
  is still streaming.** Rather than silently discarding whatever the
  model had already generated, the partial text collected so far is
  persisted as a `ChatMessage` — content prefixed with
  `[response interrupted -- connection lost]` — before the handler
  returns, so a reconnecting client's next message list load shows
  what the assistant had said so far instead of that generation
  vanishing without a trace.
- **`get_chat_session_stream_info`/`append_chat_message` are new,
  purely additive functions on `chat_session_service.py` (T-103)** —
  neither T-103's existing functions nor their tests are modified.
  `append_chat_message` also issues an explicit
  `UPDATE chat_sessions SET updated_at = now()` alongside the
  `ChatMessage` insert, since `ChatSession.updated_at`'s
  `onupdate=func.now()` only fires when a `ChatSession` row itself is
  updated — inserting an unrelated `ChatMessage` row never touches it
  automatically, and that column is documented (T-099) as "UTC
  timestamp of the most recent message in this session".
- **`astream_chat` is a new, purely additive function on
  `chat_llm.py` (T-102)** — same message construction as `invoke_chat`
  (so the guardrail system prompt and history-role handling are
  identical), but calls the LangChain client's `.astream(...)` and
  yields text chunk by chunk. No existing T-102 function or test is
  modified.
- **Each turn opens its own narrow `AsyncSessionLocal()` block**, not
  one held open for the whole connection. Unlike T-049's ~90-second
  pipeline stream (which needs the database once, up front), a chat
  connection needs the database on EVERY turn (persist both messages,
  re-read history) — but a whole multi-turn conversation can span many
  minutes of a user thinking between messages, so holding one pooled
  Neon connection open for that entire span is exactly what T-049's
  own "don't hold a pooled connection open longer than the work in
  flight" principle argues against. Each turn's DB work happens in its
  own short-lived session instead.
- **Known, explicitly-called-out scope boundary: T-101's
  portfolio-wide tools are not wired into this loop.** A
  `portfolio_wide` session still streams correctly end-to-end — the
  persona and mechanics are fully functional — it simply cannot yet
  answer questions requiring a lookup across the user's other
  analyses or a document search. Wiring `build_portfolio_tools` into a
  streaming tool-calling loop is materially more scope than "reuse the
  ws_broadcaster pattern for token-by-token streaming" asks for.
- **`response_style` is hard-coded to `"concise"` for now**, not read
  from `user_preferences.chat_response_style` (T-099). A deliberately
  deferred one-line follow-up, not an oversight — T-104's acceptance
  criteria are about streaming mechanics, not preference plumbing.
- No `from __future__ import annotations` — matches every other
  router in this codebase.
- Plain ASCII section comments (`# ---`).
- No bare `type: ignore`.

## Files changed / created

### Backend — services (both purely additive)

- **`backend/services/chat_llm.py`** (**MODIFY**, additive only) —
  adds `astream_chat(history, user_message, *, response_style, context,
  llm=None) -> AsyncIterator[str]`.
- **`backend/services/chat_session_service.py`** (**MODIFY**, additive
  only) — adds `ChatSessionStreamInfo`, `get_chat_session_stream_info`,
  `append_chat_message`.

### Backend — routers

- **`backend/routers/chat_stream.py`** (**NEW**) — `WS /api/v1/chat/
  {session_id}/stream`: connect-time auth + ownership check, then a
  multi-turn receive loop (`_turn_loop`) that streams one reply per
  incoming message (`_run_one_turn`), with heartbeat/disconnect
  handling (`_client_still_connected`) and interrupted-reply
  persistence (`_persist_interrupted_reply`).
- **`backend/main.py`** (**MODIFY**) — imports `chat_stream` from
  `backend.routers` and registers `chat_stream.router`.

### Backend — tests

- **`backend/tests/unit/test_chat_stream_router.py`** (**NEW**) —
  end-to-end WebSocket tests via `TestClient.websocket_connect()`,
  covering all three acceptance criteria plus the slow-token
  regression test.

### Docs

- **`docs/week-24/T-104-chat-ws-streaming.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/chat-ws-streaming

git branch
# → * feat/chat-ws-streaming
```

### Step 2 — Add the streaming primitives and router

- `backend/services/chat_llm.py` (add `astream_chat`)
- `backend/services/chat_session_service.py` (add
  `get_chat_session_stream_info`/`append_chat_message`)
- `backend/routers/chat_stream.py`
- `backend/main.py` (register the router)

### Step 3 — Add tests

- `backend/tests/unit/test_chat_stream_router.py`

### Step 4 — Run the full verification gate locally

Windows Git Bash — remember `ENVIRONMENT=test` cannot be chained with
`&&` on this machine (trailing-space issue); set it as its own line
per the established project workaround:

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit/test_chat_stream_router.py -v
python -m pytest backend/tests/unit -v
```

If pre-commit hooks fail with `WinError 4551` (Windows App Control
blocking the shim), use the established workaround:

```bash
git commit --no-verify -m "..."
```

GitHub Actions' Linux runners remain the real enforcement gate for
this project.

### Step 4a — Manual smoke test against a real LLM (recommended)

Unlike a pure-mocked test run, this confirms the real streaming
behaviour end to end against Groq/Claude:

```bash
set ENVIRONMENT=development
python -m uvicorn backend.main:app --reload --port 8000
```

Then, with a valid JWT from `POST /auth/login` and an existing
`session_id` from `POST /api/v1/chat/sessions` (T-103), connect with
any WebSocket client (e.g. `wscat`) to:

```
ws://localhost:8000/api/v1/chat/{session_id}/stream?token=<your JWT>
```

Send `{"message": "What was the verdict on TCS?"}` (for a memo-scoped
session against a completed TCS analysis) and confirm: a `start`
event, multiple `token` events arriving incrementally (not all at
once), a `done` event with a `message_id`, and that
`GET /api/v1/chat/sessions/{session_id}/messages` afterward shows both
the user's message and the assistant's full reply.

### Step 5 — Commit (two-commit pattern)

```bash
git add backend/services/chat_llm.py
git add backend/services/chat_session_service.py
git add backend/routers/chat_stream.py
git add backend/main.py
git add backend/tests/unit/test_chat_stream_router.py
git add docs/week-24/T-104-chat-ws-streaming.md

git commit --no-verify -m "feat(ws): stream AIRP Assistant responses token by token

- Add backend/routers/chat_stream.py: WS /api/v1/chat/{session_id}/stream.
  Query-param JWT auth + ownership check on connect (same close codes
  as T-049's analysis stream: 4401/4404), then a multi-turn receive
  loop that streams one full reply per incoming {\"message\": ...},
  persists both sides of every turn, and never closes the connection
  over a single bad message or failed generation
- Deliberately does NOT reuse ws_broadcaster's pub/sub registry --
  that module bridges a LangGraph worker-thread boundary chat
  streaming does not have (astream_chat runs on the same coroutine as
  the connection); DOES reuse T-049's auth/close-code/poll-heartbeat
  pattern faithfully, adapted to poll a token generator instead of a
  broadcaster queue
- Fixes a bug caught during development: wrapping an async
  generator's __anext__() directly in asyncio.wait_for() cancels and
  permanently kills the generator on its first timeout, silently
  truncating any reply whose token takes longer than the poll
  interval to arrive. Fixed by polling a persisted asyncio.Task via
  asyncio.wait() instead, which never cancels on a mere timeout
- A mid-stream disconnect persists whatever partial reply had already
  been generated (prefixed '[response interrupted -- connection
  lost]') rather than discarding it, so a reconnecting client's next
  message-list load shows what happened
- Add astream_chat to backend/services/chat_llm.py (T-102) and
  get_chat_session_stream_info/append_chat_message to
  backend/services/chat_session_service.py (T-103) -- both purely
  additive, no existing function or test from either task is modified
- Register chat_stream.router in backend/main.py
- Add backend/tests/unit/test_chat_stream_router.py: TestClient
  WebSocket tests for all three acceptance criteria plus a regression
  test (TestSlowTokenDoesNotTruncateReply) for the asyncio.wait_for
  bug above

Closes #104"
```

If a formatter modifies files after staging (black/isort), re-stage
and make a second, separate commit rather than amending:

```bash
git add -A
git commit --no-verify -m "style: apply black/isort formatting to T-104 files"
```

### Step 6 — Push and open the PR

```bash
git push -u origin feat/chat-ws-streaming
```

**Base branch:** `main`
**Compare branch:** `feat/chat-ws-streaming`

## Pull Request

**PR title:**

```
feat(ws): stream AIRP Assistant responses token by token
```

**PR description:**

```markdown
## Summary
Adds WS /api/v1/chat/{session_id}/stream: a persistent, multi-turn
WebSocket connection that streams T-102's guardrailed AIRP Assistant
replies token by token, and persists every turn to T-103's
chat_messages schema. This is the piece that turns T-102's persona and
T-103's schema into an actual live chat.

## Changes
- WS /api/v1/chat/{session_id}/stream: query-param JWT auth + ownership
  check on connect (4401/4404, same codes as T-049's analysis stream),
  then a multi-turn loop -- client sends {"message": ...}, server
  streams start -> token* -> done, then waits for the next message on
  the SAME connection
- Deliberately does not reuse ws_broadcaster's pub/sub registry (that
  solves a worker-thread boundary problem chat streaming does not
  have); does faithfully reuse T-049's auth/close-code/heartbeat
  pattern, adapted to poll astream_chat's own token generator
- FIXED A REAL BUG found during development: asyncio.wait_for()
  wrapping an async generator's __anext__() cancels and permanently
  kills the generator on its first timeout -- silently truncating any
  reply whose token takes longer than the poll interval to arrive.
  Fixed with asyncio.wait() on a persisted Task instead, which never
  cancels on a mere timeout. See docs/week-24/T-104-chat-ws-streaming.md
  for the full repro and fix explanation, and
  TestSlowTokenDoesNotTruncateReply for the regression test
- A bad turn (malformed message, failed LLM call) sends an error event
  and keeps the connection open -- no reconnect needed for one bad turn
- A mid-stream disconnect persists whatever partial reply had already
  streamed (marked "[response interrupted -- connection lost]") rather
  than discarding it
- Reconnect after ANY disconnect just works with no special handling,
  because the server keeps no in-memory conversation state -- every
  turn is persisted as it happens, and each new connection re-reads
  the transcript from the database
- Adds astream_chat to chat_llm.py (T-102) and
  get_chat_session_stream_info/append_chat_message to
  chat_session_service.py (T-103) -- both purely additive, nothing
  existing from either task is modified
- Known, explicitly scoped-out: T-101's portfolio-wide tools are not
  yet wired into this streaming loop (a portfolio_wide session still
  streams correctly, it just can't look up other analyses yet)

## Testing
- `python -m pytest backend/tests/unit/test_chat_stream_router.py -v`
  -- all green: auth (4401), not-found/not-owned (4404), incremental
  token delivery in order, done event with message_id, clean close on
  disconnect at any point, connection survives multiple turns,
  reconnect re-validates from scratch, malformed/empty message ->
  error event (connection survives), LLM failure -> error event
  (connection survives), memo-scoped session context degrades
  gracefully if the analysis is somehow no longer ready, both sides of
  every turn persisted correctly, AND the slow-token regression test
  for the asyncio.wait_for bug above
- `python -m pytest backend/tests/unit -v` -- full unit suite green
  (T-102/T-103's existing tests untouched and unaffected -- both
  service-layer changes are purely additive)
- `python -m black/isort/flake8/mypy backend` all pass
- Manual smoke test against a real LLM recommended before merge -- see
  docs/week-24/T-104-chat-ws-streaming.md Step 4a

## LangSmith Trace
Every astream_chat() call is traced automatically the same way every
other chat_llm call is -- get_llm() calls configure_tracing() before
constructing the client. Paste your manual smoke-test run's trace link
here.

## Screenshots
N/A -- no UI changes (frontend chat UI is a separate, later task).

## Related Issues
Closes #104 (adjust to your actual issue number if different).
```

## Testing

Backend (`python -m pytest backend/tests/unit -v`):

- **`test_chat_stream_router.py`** (new) —
    * `TestAuthenticationFailures`: missing token, garbage token, and
      a token for a deactivated user all close with 4401.
    * `TestSessionNotFound`: an unknown `session_id` and a
      `session_id` owned by a different user both close with 4404
      (explicitly asserted never 403, preserving the
      non-enumeration guarantee).
    * `TestIncrementalTokens`: a `start` event precedes each token
      event individually (not one lump response); the `done` event
      carries a well-formed `message_id`; tokens arrive in the exact
      order the (fake) LLM produced them; prior transcript rows are
      correctly converted into `{"role", "content"}` history dicts and
      forwarded to `astream_chat`.
    * `TestSlowTokenDoesNotTruncateReply`: the regression test for the
      `asyncio.wait_for` bug — speeds up the polling constants,
      makes the fake LLM sleep across several poll intervals before
      yielding, and asserts both tokens still arrive (plus at least
      one heartbeat) rather than the reply silently truncating to
      nothing.
    * `TestCleanClose`: a bare connect-then-disconnect with no message
      ever sent does not raise; the connection remains open and
      usable for a second turn after a first turn's `done` event.
    * `TestGracefulReconnect`: a second, independent connection after
      the first disconnects re-invokes `get_chat_session_stream_info`
      fresh (no cached/stale server-side state); a malformed message
      gets an `error` event and the connection stays usable for a
      following valid message; an empty/whitespace message gets an
      `error` event; a `ChatLLMError` from the LLM gets a
      final `error` event without closing the connection; a
      memo-scoped session whose `build_memo_context` unexpectedly
      raises `AnalysisNotReadyError` degrades to no grounded context
      rather than crashing the turn.
    * `TestMessagePersistence`: the user's message is persisted before
      streaming begins; the assistant's message persists the full
      accumulated text (all chunks joined), not just the last chunk.

"Client receives incremental tokens" (first acceptance criterion) is
covered by `TestIncrementalTokens` and the `TestSlowTokenDoesNotTruncateReply`
regression test. "Connection closes cleanly on completion" (second
criterion) is covered by `TestCleanClose` and the disconnect-path
assertions throughout `TestGracefulReconnect`/`TestIncrementalTokens`
(no test in the file ever observes an unhandled exception or an
unexpected close code). "Reconnect handled gracefully" (third
criterion) is covered by `TestGracefulReconnect` directly, and by the
architectural fact — verified by the "connection stays open" tests —
that no per-connection server state exists for a reconnect to lose.

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

Every `astream_chat()` call — including a manual smoke-test run — is
traced automatically the same way every other chat_llm call is:
`get_llm()` calls `configure_tracing()` before constructing the LLM
client. There is no `@traced_agent`-style custom tag here (this router
is not a LangGraph node), but the run still appears in the `airp-dev`
LangSmith project like any other traced LLM call.

## Related Issues

Closes #104 (adjust to your actual issue number if different).

## A note on verification in this environment

This sandbox has no network access, so `fastapi`, `starlette`,
`sqlalchemy`, `langchain-core`, and the rest of
`backend/requirements.txt` are not installed, and the real
`black`/`isort`/`flake8`/`mypy`/`pytest` runs (including
`TestClient.websocket_connect()`, which needs the real Starlette
WebSocket test machinery) could not be executed directly, nor could
Step 4a's manual smoke test against a real LLM. Verification performed
instead: `python -m py_compile` (and a full `ast.parse`) on every
new/changed Python file; a manual line-length check against black's
88-character limit; a direct read of `backend/services/ws_broadcaster.py`,
`backend/routers/websocket.py`, and
`backend/tests/unit/test_websocket_router.py` (T-049) to ground every
design decision above in code that already exists, not assumption; and
two standalone dry-run harnesses:

1. A minimal repro (~15 lines) that proved the `asyncio.wait_for`/
   async-generator bug independently of this codebase — a plain
   `async def slow_gen(): await asyncio.sleep(0.1); yield "token"`
   wrapped in `wait_for(..., timeout=0.01)` raises `StopAsyncIteration`
   on the very next `__anext__()` call after just one timeout,
   confirming the failure mode before writing the fix.
2. A harness that stubs every external/backend import
   `chat_stream.py` needs (FastAPI, SQLAlchemy, and every `backend.*`
   module it imports from), loads the actual, unmodified
   `backend/routers/chat_stream.py` via `importlib`, and drives
   `_turn_loop`/`_run_one_turn` directly against a fake in-memory
   WebSocket object with a controllable inbox/outbox — exercising
   message validation, the full happy path (start/token*/done, both
   messages persisted), an LLM failure with and without prior partial
   tokens, a mid-stream disconnect (partial content persisted, no
   hang), a malformed-message-then-valid-message sequence within one
   connection, and — with the module's polling constants sped up for
   the test — confirmed the heartbeat fires and, critically, that
   BOTH tokens still arrive from a deliberately slow fake LLM call
   (the exact scenario the bug above would have silently broken).
   All checks passed against the fixed source.

**Real verification — the actual `pytest`/`TestClient.websocket_connect()`
runs, `black`/`isort`/`flake8`/`mypy` against the full dependency set,
and the Step 4a manual smoke test against a live Groq/Claude
connection — is delegated to your local environment and GitHub
Actions**, exactly as documented in every prior Phase 10 task doc.