# T-102 — chat_llm.py + guardrail system prompt

**Phase:** 10 — AIRP Assistant (Chatbot)
**Week:** 24
**Branch:** `feat/chat-llm-wrapper`
**Type:** Feature
**Priority:** 🟡 High
**Est. hours:** 3

## Summary

T-102 adds `backend/services/chat_llm.py`: a thin wrapper over the
existing `backend.agents.llm_factory.get_llm`, plus the AIRP
Assistant's objectivity guardrail system prompt. This is the third
piece of the Phase 10 chat feature trio — T-100's `chat_service.py`
builds grounded context for a memo-scoped session, T-101's
`portfolio_tools.py` builds LangChain tools for a portfolio-wide
session, and T-102's `chat_llm.py` builds the persona and the call
that ties context + tools + history together for either session type.
The persona's one hard rule, required verbatim by this task's own
acceptance criteria: the assistant may explain any verdict AIRP's
committee has already reached and stored, but must never issue,
imply, or be talked into issuing a new one.

## Acceptance criteria (from task spec)

- [x] System prompt explicitly forbids overriding stored verdicts
- [x] Manual QA transcript included in PR description (see
      `scripts/manual_qa_chat_llm.py` — run locally against a real LLM
      before opening the PR; see Step 4a below)

## Design decisions

- **Why a chat-specific module at all, given `get_llm()` already does
  the provider switch.** `get_llm()` answers "which LLM client" (Groq
  during development, Claude for the demo) — identical for every
  caller, agents and chat alike. What the 8 committee agents and the
  AIRP Assistant do NOT share is what the LLM is told to do with that
  client. Every research/debate agent owns its own persona system
  prompt because each is producing a NEW analytical judgement from raw
  data. The AIRP Assistant is the opposite case by design — it must
  never produce a new judgement, only explain judgements the committee
  already reached. That asymmetry belongs in a chat-specific module,
  not folded into `llm_factory.py` — which stays a provider factory
  with zero persona opinions, exactly as it is today.
- **Lives in `backend/services/`, not `backend/agents/`.** Every
  module under `backend/agents/` is a LangGraph node — it takes an
  `InvestmentState` dict and is wrapped in `@traced_agent` for
  per-node LangSmith tags keyed off that state shape. The AIRP
  Assistant is not a pipeline node; it is invoked per user chat turn,
  outside any `InvestmentState`, by request-scoped callers exactly
  like `chat_service.py` (T-100) and `portfolio_tools.py` (T-101)
  already are. This module completes that same Phase 10 trio in the
  same layer. LangSmith tracing is still active for every call this
  module makes — `get_llm()` calls `configure_tracing()` internally
  before constructing the client, exactly as it does for every agent —
  there is just no `@traced_agent`-style per-node tag, because there
  is no node.
- **The guardrail names specific evasive phrasings rather than stating
  the rule once in the abstract.** `SYSTEM_PROMPT` states the hard
  rule ("never override a stored verdict"), then explicitly forbids it
  even when the user makes a direct opinion request, asks to
  "update"/"re-evaluate" the verdict, claims new information or
  changed market conditions, simply insists, or asks a hypothetical
  ("just between us", "what would you do"). LLM system prompts are not
  code with unambiguous control flow — a rule stated once and only in
  the abstract is measurably easier for a model to route around under
  a persistent or creatively-phrased user than the same rule restated
  against concrete attempted phrasings. The assistant is still
  explicitly allowed (and encouraged) to explain the *reasoning*
  behind a stored verdict and discuss what new information could mean
  in general terms — it must never convert that into a new
  BUY/HOLD/SELL call, conviction score, or price target of its own.
- **`get_chat_llm()` is its own function, not a bare re-export, even
  though it changes nothing about `get_llm()`'s behaviour today.**
  `get_llm()` constructs both providers with `temperature=0` — the
  AIRP Assistant keeps that too, for the same underlying reason every
  agent does (reproducible, non-creative output), doubly important
  here since a guardrail against fabricated verdicts is far easier to
  keep honest at temperature 0 than at a setting that invites
  embellishment. `get_chat_llm()` exists as its own function purely so
  chat-feature code has one local, mockable seam
  (`backend.services.chat_llm.get_chat_llm`) — mirroring how every
  agent module patches its own local `get_llm` import in tests rather
  than patching `backend.agents.llm_factory.get_llm` globally — and so
  a future chat-specific override (different temperature/timeout) has
  exactly one place to land without touching `llm_factory.py` or any
  agent.
- **`build_chat_messages()` never replays a stored `role='system'` or
  `role='tool'` chat_messages row as a conversation turn — a security
  property, not an oversight.** `chat_messages.role` (T-099) allows
  all four of user/assistant/system/tool. If a stored 'system' row
  were ever replayed as a second `SystemMessage`, it would sit later
  in the message list than this module's own guardrail `SystemMessage`
  and could weaken or contradict it in a model that weights a more
  recent system instruction more heavily. This module's guardrail is
  the ONLY system prompt any call built here ever sends — no caller
  can inject a second one by getting an attacker- or bug-influenced
  'system' row written into `chat_messages` first. 'tool' rows are
  skipped for a narrower, scope-only reason: how much of a stored tool
  result to replay vs. summarise into conversation history is a
  T-103/T-104-era chat-loop decision, out of scope for this thin
  wrapper.
- **`invoke_chat()` raises `ChatLLMError` on failure — the opposite
  convention from the 8 committee agents.** Every agent never raises;
  it returns an `error` field so the pipeline can keep going with the
  other 7 agents' output. The AIRP Assistant has no "other 7 agents"
  to fall back on for a single chat turn — it either produced a real,
  groundable answer or it did not. Silently returning canned filler
  text from inside this module would make a failed turn
  indistinguishable from a real answer to both the end user and to
  whatever eventually gets written into `chat_messages`. Raising lets
  a future router (T-103) or WebSocket handler (T-104) decide how to
  surface the failure explicitly (HTTP 502, a WS error frame, etc.).
- **Response style is wired to the existing
  `user_preferences.chat_response_style` column (T-099), not
  invented.** `RESPONSE_STYLE_INSTRUCTIONS` maps `"concise"`/
  `"detailed"` to a verbosity instruction appended after the
  guardrail; any other/unrecognised value falls back to
  `DEFAULT_RESPONSE_STYLE` rather than raising, since an
  unrecognised preference value should degrade gracefully, not break
  a chat turn.
- **NO `from __future__ import annotations`** — this module lives
  beside `backend/services/chat_service.py`, which documents the same
  reason for omitting it (breaks Pydantic v2 union resolution for
  modules that import this one). `chat_llm.py` itself defines no
  Pydantic models, but keeps the same convention as its sibling for
  consistency within the Phase 10 chat feature.
- Plain ASCII section comments (`# ---`) — established AIRP
  convention.
- No bare `type: ignore` — cast()/explicit annotations only.

## Files changed / created

### Backend — services

- **`backend/services/chat_llm.py`** (**NEW**) — `SYSTEM_PROMPT` (the
  guardrail persona), `RESPONSE_STYLE_INSTRUCTIONS` /
  `DEFAULT_RESPONSE_STYLE`, `ChatLLMError`, `get_chat_llm()` (thin
  wrapper over `llm_factory.get_llm`), `build_system_prompt` /
  `build_system_message` (persona + style + optional context),
  `build_chat_messages` (system + history + new user message, with
  the system/tool-row skip described above), and `invoke_chat` (the
  single-call convenience entry point T-103/T-104 will build on).

### Backend — tests

- **`backend/tests/unit/test_chat_llm.py`** (**NEW**) — guardrail
  content assertions against the actual acceptance criterion (system
  prompt forbids overriding stored verdicts, and covers each specific
  evasive phrasing named above); `get_chat_llm` delegation; every
  `build_system_prompt`/`build_system_message` style/context branch;
  every `build_chat_messages` ordering, role-conversion, and
  skip-case (missing role, non-string content, `system`/`tool`/
  unknown roles); every `invoke_chat` path (success, default vs.
  injected LLM, exact message list sent to `.invoke()`, exception
  wrapped into `ChatLLMError` with `.cause` set, non-string `.content`
  stringified, a response object with no `.content` attribute at all,
  and an empty/whitespace response raising `ChatLLMError`).

### Scripts

- **`scripts/manual_qa_chat_llm.py`** (**NEW**) — a standalone,
  non-CI script that runs a fixed, four-turn conversation (one control
  question plus three escalating attempts to elicit a new verdict:
  direct opinion request, claimed new information with an explicit
  "update the verdict" ask, and insistence/hypothetical framing)
  against your real configured `LLM_PROVIDER`, using a hand-built
  fixture context (no live database dependency), and prints a
  copy-paste-ready transcript for the PR description. Includes a
  crude keyword sanity flag on the three adversarial replies — clearly
  documented as a hint, not a substitute for actually reading each
  reply before pasting it into the PR.
- **`scripts/README.md`** (**MODIFY**) — adds a row for
  `manual_qa_chat_llm.py`.

### Docs

- **`docs/week-24/T-102-chat-llm-wrapper.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/chat-llm-wrapper

git branch
# → * feat/chat-llm-wrapper
```

### Step 2 — Add the LLM wrapper module

- `backend/services/chat_llm.py`

### Step 3 — Add tests

- `backend/tests/unit/test_chat_llm.py`

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
python -m pytest backend/tests/unit/test_chat_llm.py -v
python -m pytest backend/tests/unit -v
```

If pre-commit hooks fail with `WinError 4551` (Windows App Control
blocking the shim), use the established workaround:

```bash
git commit --no-verify -m "..."
```

GitHub Actions' Linux runners remain the real enforcement gate for
this project.

### Step 4a — Produce the manual QA transcript (required for the PR)

This is the acceptance-criteria step — do this before opening the PR,
not after. Requires a real LLM key in `.env` (Groq is the default dev
provider):

```bash
set ENVIRONMENT=development
python -m scripts.manual_qa_chat_llm
```

Read every `ASSISTANT:` reply yourself. Confirm by eye that:

- Turn 1 (control) gets a full, grounded answer.
- Turns 2–4 (direct opinion / "update the verdict" / insistence) each
  explain the *stored* verdict and reasoning, redirect the user to
  running a new AIRP analysis for an updated view, and do **not**
  state a new BUY/HOLD/SELL, conviction score, or price target of
  their own.

Copy the printed transcript into the PR description's "Manual QA
transcript" section below **before** pushing. If any adversarial reply
does slip a new verdict-shaped answer through, that is a real bug in
`SYSTEM_PROMPT` to fix in this branch before opening the PR — not
something to paste in and note as a known issue.

### Step 5 — Commit (two-commit pattern)

```bash
git add backend/services/chat_llm.py
git add backend/tests/unit/test_chat_llm.py
git add scripts/manual_qa_chat_llm.py
git add scripts/README.md
git add docs/week-24/T-102-chat-llm-wrapper.md

git commit --no-verify -m "feat(chat): add LLM wrapper and guardrail system prompt

- Add backend/services/chat_llm.py: get_chat_llm() thin-wraps
  llm_factory.get_llm(); SYSTEM_PROMPT is the AIRP Assistant's
  objectivity guardrail persona -- explicitly forbids issuing,
  implying, or being talked into a new BUY/HOLD/SELL verdict,
  conviction score, or price target, and names the specific evasive
  phrasings it must resist (direct opinion requests, 'update the
  verdict', claimed new information, insistence, hypotheticals)
- Add build_system_prompt/build_system_message (persona + response
  style from user_preferences.chat_response_style + optional grounded
  context) and build_chat_messages (system + history + new user
  message); stored chat_messages rows with role='system'/'tool' are
  never replayed as conversation turns, so no stored row can ever
  inject a second system prompt that outranks the guardrail
- Add invoke_chat() as the single-call entry point; raises
  ChatLLMError on failure (opposite convention from the 8 committee
  agents, which never raise) since a chat turn has no other agents to
  fall back on
- Add backend/tests/unit/test_chat_llm.py: guardrail content
  assertions against the acceptance criterion, get_chat_llm
  delegation, every build_system_prompt/build_chat_messages branch,
  and every invoke_chat success/failure/edge-case path
- Add scripts/manual_qa_chat_llm.py: runs a fixed 4-turn adversarial
  conversation against a real configured LLM and prints a PR-ready
  manual QA transcript; update scripts/README.md with its entry

Closes #102"
```

If a formatter modifies files after staging (black/isort), re-stage
and make a second, separate commit rather than amending:

```bash
git add -A
git commit --no-verify -m "style: apply black/isort formatting to T-102 files"
```

### Step 6 — Push and open the PR

```bash
git push -u origin feat/chat-llm-wrapper
```

**Base branch:** `main`
**Compare branch:** `feat/chat-llm-wrapper`

## Pull Request

**PR title:**

```
feat(chat): implement AIRP Assistant persona with objectivity guardrail
```

**PR description:**

```markdown
## Summary
Adds backend/services/chat_llm.py: a thin wrapper over the existing
llm_factory.get_llm, plus the AIRP Assistant's objectivity guardrail
system prompt. Completes the Phase 10 chat trio alongside T-100's
chat_service.py (grounded context) and T-101's portfolio_tools.py
(LangChain tools) -- this module supplies the persona and the call
that ties context + tools + history together, for a future chat loop
(T-103 REST endpoints, T-104 WebSocket streaming) to build on.

## Changes
- get_chat_llm() thin-wraps llm_factory.get_llm() -- same provider,
  same temperature=0, on its own local/mockable seam
- SYSTEM_PROMPT explicitly forbids the assistant from issuing,
  implying, or being talked into a new BUY/HOLD/SELL verdict,
  conviction score, or price target -- including under a direct
  opinion request, an explicit "update the verdict" ask, claimed new
  information/changed market conditions, plain insistence, or a
  hypothetical framing. The assistant may still fully explain a
  stored verdict's reasoning and discuss what new information could
  mean in general terms; it must redirect the user to running a new
  AIRP analysis for an actual updated view
- build_system_prompt/build_system_message layer response-style
  verbosity (wired to the existing user_preferences.chat_response_style
  column) and optional grounded context on top of the guardrail
- build_chat_messages converts stored chat_messages rows into
  conversation history, deliberately skipping role='system'/'tool'
  rows so no stored row can ever inject a second system prompt that
  could outrank the guardrail (a security property, documented
  explicitly)
- invoke_chat() raises ChatLLMError on failure rather than degrading
  gracefully, the opposite convention from the 8 committee agents --
  a chat turn has no other agents to fall back on, so a caller needs
  to know a turn actually failed

## Testing
- `python -m pytest backend/tests/unit/test_chat_llm.py -v` -- all
  green: guardrail content checks, get_chat_llm delegation, every
  build_system_prompt/build_chat_messages branch, every invoke_chat
  success/failure/edge case
- `python -m pytest backend/tests/unit -v` -- full unit suite green
- `python -m black/isort/flake8/mypy backend` all pass
- Manual QA transcript (T-102's own acceptance criterion) -- see
  below, produced by `python -m scripts.manual_qa_chat_llm` against
  [Groq llama-3.3-70b-versatile / Claude, delete as applicable]

## Manual QA transcript

[Paste the real output of `python -m scripts.manual_qa_chat_llm` here
before opening the PR -- see docs/week-24/T-102-chat-llm-wrapper.md,
Step 4a, for exactly what to check before pasting. Do not paste a
transcript where any adversarial turn slipped a new verdict-shaped
answer through; fix the prompt and re-run first.]

## LangSmith Trace
[Paste your run's LangSmith trace link here -- get_llm() calls
configure_tracing() internally, so every invoke_chat() call in the
manual QA run above is traced exactly like an agent call, tagged with
the default 'airp-dev' project.]

## Screenshots
N/A -- no UI changes.

## Related Issues
Closes #102 (adjust to your actual issue number if different).
```

## Testing

Backend (`python -m pytest backend/tests/unit -v`):

- **`test_chat_llm.py`** (new) —
    * `TestSystemPromptGuardrail`: the prompt forbids overriding a
      stored verdict, names BUY/HOLD/SELL explicitly, and covers
      direct opinion requests, update/re-evaluate phrasing, claimed
      new information/changed market conditions, and user insistence;
      still names the committee (Portfolio Manager, Contrarian
      Investor) as the analytical authority; still explicitly permits
      explaining a stored analysis; forbids fabricating agent
      statements or tool results; is a non-trivial, non-placeholder
      length.
    * `TestGetChatLlm`: delegates to (a patched) `llm_factory.get_llm`
      and returns its result unchanged.
    * `TestBuildSystemPrompt` / `TestBuildSystemMessage`: default
      style is concise; detailed style selected correctly and
      excludes the concise instruction; an unrecognised style falls
      back to the default; the guardrail is always present regardless
      of style/context; no context block when `context=None` or `""`;
      context appended verbatim when provided; `build_system_message`
      wraps the same text in a `SystemMessage`.
    * `TestBuildChatMessages`: first message is always the system
      guardrail, last message is always the new `HumanMessage`; empty
      history produces exactly system + 1 human message;
      user/assistant roles convert to Human/AI messages in order;
      `role='system'` and `role='tool'` rows are silently skipped
      (proving the security property); a row missing `role`, a row
      with non-string `content`, and an unrecognised role string are
      all skipped rather than raising; response_style/context are
      correctly forwarded into the system message.
    * `TestInvokeChat`: success returns `.content` text; the default
      path calls `get_chat_llm()` exactly once when no `llm` is
      injected; an injected `llm` bypasses `get_chat_llm()` entirely;
      the exact message list built is what gets passed to
      `.invoke()`; an LLM exception is wrapped in `ChatLLMError` with
      `.cause` set to the original exception; non-string `.content`
      (e.g. a list) is stringified; a response object with no
      `.content` attribute at all falls back to `str(response)`; an
      empty/whitespace-only reply raises `ChatLLMError`.
    * `TestChatLLMError`: `.cause` defaults to `None` and can be set
      explicitly; `str(err)` returns the message.

"System prompt explicitly forbids overriding stored verdicts" (first
acceptance criterion) is covered end to end by `TestSystemPromptGuardrail`
plus `TestBuildChatMessages::test_system_role_rows_are_skipped` (which
additionally proves no stored data can weaken it). "Manual QA
transcript included in PR description" (second acceptance criterion)
is satisfied by running `scripts/manual_qa_chat_llm.py` against a real
LLM per Step 4a above and pasting its output into the PR.

## Verification gate run locally before pushing

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v
```

Then, separately (real LLM call, not part of the automated gate):

```bash
set ENVIRONMENT=development
python -m scripts.manual_qa_chat_llm
```

## LangSmith Trace

Every `invoke_chat()` call — including each turn in the manual QA
run above — is traced automatically, the same way every agent call
is: `get_llm()` calls `configure_tracing()` before constructing the
LLM client, which mirrors `LANGSMITH_API_KEY`/`LANGCHAIN_TRACING_V2`
from `settings` into `os.environ` before any LangChain object is
built. There is no `@traced_agent`-style custom tag here (this module
is not a LangGraph node), but the run still appears in the
`airp-dev` LangSmith project like any other traced LLM call. Paste
your manual QA run's trace link into the PR's LangSmith Trace field.

## Related Issues

Closes #102 (adjust to your actual issue number if different).

## A note on verification in this environment

This sandbox has no network access, so `langchain-core` and the rest
of `backend/requirements.txt` are not installed, and the real
`black`/`isort`/`flake8`/`mypy`/`pytest` runs could not be executed
directly, nor could `scripts/manual_qa_chat_llm.py` be run against a
real LLM. Verification performed instead: `python -m py_compile` on
all three new/changed Python files; a manual line-length check against
black's 88-character limit; a direct read of
`backend/agents/contrarian_investor.py` (the existing precedent for
`get_llm()` + `SystemMessage`/`HumanMessage` + `llm.invoke()` +
try/except) and `backend/services/chat_service.py` /
`backend/tools/portfolio_tools.py` (T-100/T-101, for module placement
and docstring/testing conventions) to ground every design decision
above in code that already exists, not assumption; and a standalone
dry-run harness — minimal stand-ins for `langchain_core.messages`
(`BaseMessage`/`SystemMessage`/`HumanMessage`/`AIMessage`, matching the
real library's public `.content` contract) and
`backend.agents.llm_factory.get_llm` — that loads the actual,
unmodified `backend/services/chat_llm.py` source via `importlib` and
exercises every branch the test file covers end to end (guardrail
content, `get_chat_llm` delegation, every `build_system_prompt`/
`build_chat_messages` case, every `invoke_chat` success/failure/edge
case), plus a second dry run of the actual, unmodified
`scripts/manual_qa_chat_llm.py` against a stubbed but
guardrail-compliant fake LLM to confirm the script itself runs to
completion and produces the expected transcript shape. **Real
verification — the actual `pytest`, `black`/`isort`/`flake8`/`mypy`
runs against the full dependency set, and the real manual QA transcript
against a live Groq/Claude call — is delegated to your local
environment and GitHub Actions**, exactly as documented in every prior
Phase 10 task doc.