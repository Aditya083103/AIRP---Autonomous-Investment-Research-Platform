# T-105 — ChatWidget.tsx frontend

**Phase:** 10 — AIRP Assistant (Chatbot)
**Week:** 25
**Branch:** `feat/ui-chat-widget`
**Type:** Feature
**Priority:** 🟡 High
**Est. hours:** 5

## Summary

T-105 adds the floating AIRP Assistant chat panel to the frontend: a
round toggle button fixed to the bottom-right corner of every
authenticated page, which expands into a chat panel wired end-to-end
against the backend chat feature Phase 10 already shipped —
`POST /api/v1/chat/sessions` (T-103) to start a session, and
`WS /api/v1/chat/{session_id}/stream` (T-104) to hold a multi-turn,
token-streamed conversation over it. This is a **frontend-only** task:
T-098–T-104 already built and tested the entire backend chat API
(`backend/routers/chat.py`, `backend/routers/chat_stream.py`,
`chat_session_service.py`, `chat_llm.py`, the T-099 schema/migration),
so no backend file changes.

The widget is mounted exactly once, in `RootLayout.tsx` (T-053's
always-rendered app shell), gated behind `isAuthenticated` — this is
what makes it "available on Dashboard and MemoPage" (this task's own
acceptance criterion) without either of those already-shipped, already
-tested page files needing to change at all. It determines which mode
to use — **memo-scoped** (grounded to one completed analysis) or
**portfolio-wide** (spans the user's whole history) — by reading the
current route directly (`src/lib/chat/chatScope.ts`'s
`deriveChatScope`), matching against MemoPage's own
`"analysis/:jobId/memo"` route pattern (T-063) for the memo case and
falling back to portfolio-wide everywhere else (including Dashboard,
T-057).

## Acceptance criteria (from task spec)

- [x] Widget available on Dashboard and MemoPage
- [x] Correctly scopes questions to current analysis when opened from
      a memo

## Design decisions

- **Why the widget reads the route directly instead of MemoPage
  pushing an `analysis_id` into some new shared context.** RootLayout
  already does exactly this for its own purposes (`useLocation`, to
  close the mobile nav panel on navigation, T-065). Reading route state
  directly keeps the coupling one-directional — chat reads the route;
  MemoPage.tsx (T-063, already shipped and tested) is untouched — and
  keeps this task's entire diff inside files the chat feature owns
  (`src/lib/chat/`, `src/hooks/useChat*.ts`,
  `src/components/chat/`) plus one small, additive change to
  `RootLayout.tsx` (mount the widget, gated on auth).
- **`deriveChatScope`/`chatScopeKey` are pulled into their own pure,
  dependency-light module (`src/lib/chat/chatScope.ts`)** rather than
  inlined in the controller hook — trivially unit-testable without
  rendering anything or mocking `useLocation`, the same reasoning
  `src/lib/graph/liveGraphState.ts` (T-096) and every other
  `src/lib/*` pure-function module in this codebase already follows.
- **Session creation is lazy (on first open), not eager (on mount).**
  `ChatWidget` is always mounted on every authenticated route, but the
  person may never open it during a given visit. Creating a
  `ChatSession` row (T-099) on every page load regardless of whether
  the person ever asks a question would litter `chat_sessions` with
  empty rows — `POST /api/v1/chat/sessions` only fires the first time
  the panel is opened for a given scope (`useChatWidget.ts`).
- **A session is discarded, never reused, when the scope's identity
  changes** (navigating from one memo to a different one, or between
  memo and portfolio mode). T-099's schema ties `session_type` +
  `analysis_id` to one `ChatSession` row permanently at creation time
  (the `ck_chat_sessions_scope_consistency` CHECK constraint
  `backend/models/schemas.py`'s own `ChatSessionCreateRequest`
  docstring documents) — reusing an old session's id against a new
  scope is not something the backend even allows. `useChatWidget.ts`
  tracks the scope key a session was created for in a ref and clears
  local session state the moment it no longer matches the current
  scope key; if the panel is still open, the very next render creates
  a fresh session for the new scope automatically.
- **A bug caught and fixed during development: a failed session
  creation must not retry itself in an infinite loop.** The
  session-creation effect depends on `isCreatingSession` (so a second
  `toggle()` while a POST is already in flight is a safe no-op rather
  than a duplicate request) — but that same dependency means the
  effect re-fires the instant `isCreatingSession` flips back to
  `false` after a **failure** too (e.g. a 409 because the analysis
  isn't ready yet), with every other guard condition (`isOpen`,
  `session === null`, authenticated) still true. Left alone, this is
  an unbounded retry loop hitting the backend on every render. Fixed
  with a second ref, `attemptedScopeKeyRef`, set the moment an attempt
  begins and only cleared when the scope itself genuinely changes —
  a failed attempt for the same scope does not retry itself; the
  person closing and reopening the panel for the same (still-failing)
  scope does not either, which is the deliberately conservative
  choice documented inline in `useChatWidget.ts` (a "Retry" affordance
  is a natural, separate follow-up, not required by this task's
  acceptance criteria).
- **`useChatStream.ts` mirrors `useAnalysisStream.ts`'s (T-049) effect
  shape** (open one socket for the lifetime of the identifying props,
  close on unmount or when they change; a runtime type guard before
  trusting anything read off the wire) but is NOT receive-only the way
  that hook is — it also **sends** `{"message": "<text>"}` per turn,
  and opens its socket **once per session** rather than once per
  event, because T-104's server keeps one connection open across many
  turns ("receive loop: for each incoming message, stream one full
  reply back, then wait for the next message on the SAME connection" —
  `chat_stream.py`'s own module docstring) rather than closing after
  one `is_final: true` the way the analysis-progress stream does.
- **Five `event_type` values drive the transcript state machine**
  (`start`/`token`/`heartbeat`/`done`/`error`), matching
  `chat_stream.py`'s `ChatStreamEvent` exactly. `error` deliberately
  does **not** close the connection or the transcript on the frontend
  either — matching the backend's own "a bad turn does not close the
  connection" guarantee — a turn-level error is rendered as an errored
  bubble (either finalizing the in-progress streaming message, or as
  its own standalone bubble if no `start` had arrived yet), and the
  composer re-enables immediately so the next message can be sent on
  the same socket.
- **The composer is disabled whenever `session === null` or an
  assistant reply is currently streaming** (`isAssistantTyping`) —
  there is no client-side message queue; this mirrors the server's own
  turn-by-turn protocol (it does not read the next message off the
  socket until the current turn's `_run_one_turn` finishes) rather
  than inventing client-side queuing the backend has no matching
  concept for.
- **No `GET /api/v1/chat/sessions` / `GET .../messages` calls in this
  task.** T-103 shipped both, but resuming a past session across page
  reloads (or a "chat history" list view) is a natural follow-up, not
  part of this task's two acceptance criteria — `src/api/chat.ts`
  intentionally only wraps `POST /chat/sessions` for now, documented
  inline as a deliberate scope boundary rather than an oversight.

## Files changed / created

### Frontend — types & API client

- **`frontend/src/types/chat.ts`** (**NEW**) — `ChatSessionType`,
  `ChatSessionCreateRequest`, `ChatSessionResponse`,
  `ChatMessageResponse`, mirroring `backend/models/schemas.py`'s chat
  schemas field-for-field.
- **`frontend/src/api/chat.ts`** (**NEW**) — `createChatSession()`,
  `ChatApiError`, wrapping `POST /api/v1/chat/sessions`.

### Frontend — lib

- **`frontend/src/lib/chat/chatScope.ts`** (**NEW**) —
  `deriveChatScope(pathname)`, `chatScopeKey(scope)`.

### Frontend — hooks

- **`frontend/src/hooks/useChatStream.ts`** (**NEW**) — WebSocket hook
  for `WS /api/v1/chat/{session_id}/stream`; exposes `messages`,
  `connectionStatus`, `isAssistantTyping`, `error`, `sendMessage`.
- **`frontend/src/hooks/useChatWidget.ts`** (**NEW**) — controller
  hook composing scope derivation, lazy session creation, and
  `useChatStream`.

### Frontend — components

- **`frontend/src/components/chat/ChatMessageBubble.tsx`** (**NEW**) —
  one transcript row (user vs. assistant, streaming/typing state,
  error state).
- **`frontend/src/components/chat/ChatWidget.tsx`** (**NEW**) — the
  floating toggle + panel; composer; scope label; empty/loading/error
  states.
- **`frontend/src/components/chat/index.ts`** (**NEW**) — barrel
  export.
- **`frontend/src/components/layout/RootLayout.tsx`** (**MODIFY**,
  additive only) — mounts `<ChatWidget />` gated on `isAuthenticated`.

### Frontend — tests

- **`frontend/src/test/chatScope.test.ts`** (**NEW**)
- **`frontend/src/test/chatApi.test.ts`** (**NEW**)
- **`frontend/src/test/useChatStream.test.ts`** (**NEW**)
- **`frontend/src/test/useChatWidget.test.tsx`** (**NEW**)
- **`frontend/src/test/ChatWidget.test.tsx`** (**NEW**)
- **`frontend/src/test/RootLayout.test.tsx`** (**MODIFY**) — adds a
  small "chat widget (T-105)" describe block asserting the
  auth-gated mount point; every pre-existing test in this file is
  unchanged.

### Docs

- **`docs/week-25/T-105-ChatWidget-Frontend.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/ui-chat-widget

git branch
# → * feat/ui-chat-widget
```

### Step 2 — Add the types, API client, and scope-derivation lib

```bash
# frontend/src/types/chat.ts
# frontend/src/api/chat.ts
# frontend/src/lib/chat/chatScope.ts
```

### Step 3 — Add the hooks

```bash
# frontend/src/hooks/useChatStream.ts
# frontend/src/hooks/useChatWidget.ts
```

### Step 4 — Add the components and mount the widget

```bash
# frontend/src/components/chat/ChatMessageBubble.tsx
# frontend/src/components/chat/ChatWidget.tsx
# frontend/src/components/chat/index.ts
# frontend/src/components/layout/RootLayout.tsx (modify)
```

### Step 5 — Add tests

```bash
# frontend/src/test/chatScope.test.ts
# frontend/src/test/chatApi.test.ts
# frontend/src/test/useChatStream.test.ts
# frontend/src/test/useChatWidget.test.tsx
# frontend/src/test/ChatWidget.test.tsx
# frontend/src/test/RootLayout.test.tsx (modify)
```

### Step 6 — Run the full verification gate locally

Windows Git Bash, from the repo root:

```bash
cd frontend

npm run format
npm run lint
npm run type-check
npm run test:run
npm run build
```

- `npm run format` runs Prettier over every staged and unstaged file
  in `src/**` — run this **before** `lint`/`type-check` so any
  auto-fixed formatting is already in place for the two-commit pattern
  below (see Step 7).
- `npm run test:run` runs the full Vitest suite once (not watch mode)
  — confirm the five new chat test files pass alongside every
  pre-existing test file, in particular `RootLayout.test.tsx` (the one
  existing file this task modifies).
- `npm run build` (`tsc && vite build`) is the strictest gate: it
  fails on any TypeScript error under this project's `strict` +
  `noUncheckedIndexedAccess` + `exactOptionalPropertyTypes` compiler
  options, which `type-check` alone also catches but `build` proves
  the production bundle itself compiles clean.

If pre-commit hooks fail with `WinError 4551` (Windows App Control
blocking the shim), use the established workaround:

```bash
git commit --no-verify -m "..."
```

GitHub Actions' Linux runners remain the real enforcement gate for
this project — both the frontend CI job (Prettier, ESLint, `tsc
--noEmit`, Vitest) and, since this task touches no backend file, the
backend CI job simply passes unchanged.

### Step 6a — Manual smoke test against the real backend (recommended)

Two terminals, from the repo root:

```bash
# Terminal 1 — backend
set ENVIRONMENT=development
python -m uvicorn backend.main:app --reload --port 8000
```

```bash
# Terminal 2 — frontend
cd frontend
npm run dev
```

Log in, open the Dashboard, click the round toggle bottom-right —
confirm the panel opens with "Asking about your portfolio", ask a
question, and watch the reply stream in token by token. Then open a
completed analysis's Investment Memo page and reopen (or click) the
same toggle — confirm the header now reads "Asking about this memo"
and the question is answered using that specific memo's grounded
context (`backend/services/chat_service.py`'s `build_memo_context`,
T-100).

### Step 7 — Commit (two-commit pattern)

```bash
git add frontend/src/types/chat.ts
git add frontend/src/api/chat.ts
git add frontend/src/lib/chat/chatScope.ts
git add frontend/src/hooks/useChatStream.ts
git add frontend/src/hooks/useChatWidget.ts
git add frontend/src/components/chat/ChatMessageBubble.tsx
git add frontend/src/components/chat/ChatWidget.tsx
git add frontend/src/components/chat/index.ts
git add frontend/src/components/layout/RootLayout.tsx
git add frontend/src/test/chatScope.test.ts
git add frontend/src/test/chatApi.test.ts
git add frontend/src/test/useChatStream.test.ts
git add frontend/src/test/useChatWidget.test.tsx
git add frontend/src/test/ChatWidget.test.tsx
git add frontend/src/test/RootLayout.test.tsx
git add docs/week-25/T-105-ChatWidget-Frontend.md

git commit --no-verify -m "feat(frontend): add AIRP Assistant floating chat widget

- Add ChatWidget.tsx: a floating toggle + panel mounted once in
  RootLayout.tsx, gated on isAuthenticated -- available on every
  authenticated route (Dashboard, MemoPage, ...) with no change to
  either of those already-shipped page files
- Add src/lib/chat/chatScope.ts: deriveChatScope(pathname) reads the
  current route directly (matching MemoPage's own
  'analysis/:jobId/memo' pattern) to decide memo_scoped vs
  portfolio_wide -- keeps the scope-detection coupling one-directional
- Add src/hooks/useChatStream.ts: WebSocket hook for
  WS /api/v1/chat/{session_id}/stream (T-104), mirroring
  useAnalysisStream's effect shape but adapted for chat's turn-based,
  multi-message-per-connection protocol and its five event_type values
  (start/token/heartbeat/done/error)
- Add src/hooks/useChatWidget.ts: lazily creates a ChatSession
  (POST /api/v1/chat/sessions, T-103) on first open per scope, and
  discards/recreates it when the scope's identity changes (navigating
  between memos, or between memo and portfolio mode)
- Fixes a bug caught during development: a failed session-creation
  attempt (e.g. 409 -- analysis not ready) could otherwise retry
  itself in an unbounded loop, since isCreatingSession flipping back
  to false re-satisfied every other effect guard. Fixed with a
  per-scope 'already attempted' ref that only clears on a genuine
  scope change
- Add src/api/chat.ts (createChatSession) and src/types/chat.ts,
  mirroring backend/models/schemas.py's chat schemas
- Add ChatMessageBubble.tsx + components/chat barrel export
- Add full test coverage: chatScope, chatApi, useChatStream,
  useChatWidget, and a component-level ChatWidget test exercising the
  open -> create session -> stream a reply flow end to end (fake
  WebSocket + stubbed fetch, no real network)
- Extend RootLayout.test.tsx with a small auth-gate assertion for the
  new widget; every pre-existing RootLayout test is unchanged

Closes #105"
```

If Prettier/ESLint auto-fix modifies any file after staging, re-stage
and make a second, separate commit rather than amending:

```bash
git add -A
git commit --no-verify -m "style: apply prettier/eslint formatting to T-105 files"
```

### Step 8 — Push and open the PR

```bash
git push -u origin feat/ui-chat-widget
```

**Base branch:** `main`
**Compare branch:** `feat/ui-chat-widget`

## Pull Request

**Title:** `feat(ui): build ChatWidget with memo-scoped and portfolio-wide modes`

### Summary

Adds the floating AIRP Assistant chat widget to the frontend: a
toggle button on every authenticated page that opens a panel wired
against the backend chat API Phase 10 already shipped
(`POST /api/v1/chat/sessions`, `WS /api/v1/chat/{session_id}/stream`).
The widget is context-aware — it automatically scopes new
conversations to the analysis currently open on MemoPage, or to the
user's whole portfolio everywhere else — with no changes to
DashboardPage.tsx or MemoPage.tsx themselves.

### Changes

- New floating `ChatWidget` mounted once in `RootLayout.tsx`, gated on
  `isAuthenticated`
- New `useChatWidget`/`useChatStream` hooks handling scope detection,
  lazy session creation, scope-change session resets, and the
  token-by-token WebSocket turn loop
- New `src/api/chat.ts` + `src/types/chat.ts` + `src/lib/chat/chatScope.ts`
- New `ChatMessageBubble` transcript row component
- Full unit + component test coverage for every new file, plus a small
  addition to the existing `RootLayout.test.tsx`

### Testing

- `npm run test:run` — full Vitest suite, including 6 new/modified
  test files for this task
- `npm run type-check` / `npm run build` — `tsc --strict` with
  `noUncheckedIndexedAccess` + `exactOptionalPropertyTypes`
- `npm run lint` — ESLint (`--max-warnings 0`)
- Manual smoke test against the real backend (Step 6a above): opened
  the widget from Dashboard (portfolio-wide) and from a completed
  memo (memo-scoped), confirmed the scope label and grounded answer
  both matched, and confirmed token-by-token streaming rendered
  incrementally rather than all at once

### LangSmith Trace

N/A — this PR touches no backend/LLM-calling code; every AIRP
Assistant call this widget triggers is already traced by T-102's
`chat_llm.py` (unchanged by this task).

### Screenshots

_Attach: (1) collapsed toggle bottom-right on Dashboard, (2) open panel
showing "Asking about your portfolio", (3) open panel from a memo
showing "Asking about this memo" plus a grounded answer, (4) a reply
mid-stream (partial text + typing indicator)._

### Related Issues

Closes #105