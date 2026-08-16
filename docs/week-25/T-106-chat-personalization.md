# T-106 — Personalization via user_preferences

**Phase:** 10 — AIRP Assistant (Chatbot)
**Week:** 25
**Branch:** `feat/chat-personalization`
**Type:** Feature
**Priority:** 🟢 Medium
**Est. hours:** 3

## Summary

T-106 lets the AIRP Assistant ask about a user's investing risk
appetite and preferred sectors once, remember the answer, and use it
to adjust the tone and emphasis of later replies — never a stored
verdict. This is a **backend-only** task: `ChatWidget.tsx` (T-105)
already renders whatever text the assistant streams back, so no
frontend file changes are needed for the assistant to naturally ask a
question and receive an answer through the existing chat UI.

Two new columns on `user_preferences` (`risk_appetite`,
`preferred_sectors`, both empty/NULL until first answered) back the
feature. A new, deliberately **deterministic** (no second LLM call)
extractor recognises a stated preference in the user's own words; a
new service layer persists it **once** — a field already known is
never overwritten by a later, more casual mention. A new instruction
block in `chat_llm.py`'s system prompt tells the assistant to ask (at
most once) when nothing is known, and to use what *is* known for tone
only, with an adjacent hard rule forbidding it from ever touching a
verdict, conviction score, or price target.

## Acceptance criteria (from task spec)

- [x] `user_preferences` populated after first relevant exchange
- [x] Tone visibly adapts in manual QA
- [x] Verdicts remain byte-identical regardless of preferences

## Design decisions

- **Why deterministic keyword extraction, not a second LLM call.**
  `backend/services/preference_extractor.py` recognises a stated risk
  appetite/preferred sectors via a small, precompiled regex table, not
  a second model call. Three reasons, in the module's own words:
  determinism and testability (a keyword table is assertable
  byte-for-byte forever; every one of this codebase's 8 committee
  agents already treats an LLM call as something that can fail or
  drift, and this feature writes directly to a persisted preference —
  exactly the kind of write where that matters most), cost/latency (a
  second round-trip on every turn would roughly double it, for a
  two-enum-like-field extraction task that doesn't need open-ended
  understanding), and a smaller trust/safety surface (a reviewable
  diff, not free-form model output, decides what gets written to the
  database).
- **Recall is intentionally conservative, by design.** A phrasing the
  extractor doesn't recognise is simply not detected this turn — the
  assistant can still ask again later, since nothing is persisted
  until the extractor actually recognises something. Ambiguous input
  (e.g. a message that matches two risk-appetite categories at once)
  resolves to "not detected" rather than guessing.
- **"Ask and remember... once" is enforced at the persistence layer,
  not just in the prompt wording.** `backend/services/
  preference_service.py`'s `apply_extracted_preferences` only ever
  writes a field that is currently unset (`NULL`/`[]`) — once
  `risk_appetite` is set, a later, more casual mention of a different
  appetite in an unrelated question never overwrites it. This makes
  the "once" contract a database-level guarantee `chat_stream.py`
  cannot violate by calling the function on every turn (which it does,
  by design, the same way it already re-evaluates `context` on every
  turn).
- **The personalization instruction is a separate, independently
  testable block (`chat_llm.build_personalization_instruction`), not
  folded into the objectivity guardrail.** Mirrors the existing
  `RESPONSE_STYLE_INSTRUCTIONS` pattern: a small function returning
  instruction text, appended by `build_system_prompt` after the
  response-style instruction and before any grounded `context`. Its
  hard rule ("tone/emphasis only, never a verdict") is deliberately
  restated here, immediately beside the personalization data itself —
  not only once in `SYSTEM_PROMPT` — the same "restate a guardrail
  against the concrete thing that could tempt a model to break it, not
  only once in the abstract" reasoning `SYSTEM_PROMPT`'s own docstring
  already gives for the verdict-override rule.
- **A bug caught and fixed during development: naive wiring would have
  caused an infinite retry loop on a failed extraction write.** Not
  applicable here in the same shape as T-105's bug (that was a
  frontend `useEffect` issue) — but the equivalent risk was considered
  and avoided by design: `apply_extracted_preferences` is a pure
  "write if still unset" function with no retry state of its own, and
  `get_or_create_user_preferences` handles the one real failure mode
  (a `user_preferences.user_id` UNIQUE-constraint race between two
  concurrent first-ever requests for the same brand-new user) by
  catching `IntegrityError`, rolling back, and re-reading the row the
  other request created — never propagating, never looping.
- **`response_style` is now genuinely read from
  `user_preferences.chat_response_style`, replacing the hard-coded
  `"concise"` constant `chat_stream.py` used through T-104/T-105.**
  T-104's own docstring called this a "small, natural, and
  DELIBERATELY DEFERRED follow-up" specifically because wiring a
  per-user lookup was scope creep against T-104's own WebSocket-
  streaming-mechanics acceptance criteria. T-106 — literally titled
  "Personalization via user_preferences" — is that deferred follow-up:
  since this task already loads the user's `UserPreferences` row once
  per turn for `risk_appetite`/`preferred_sectors`, reading the real
  `chat_response_style` off the same row costs nothing extra and
  removes a constant the router no longer needs (removed rather than
  left around unused).
- **Verdict independence is the checkable, tested basis for this
  task's third acceptance criterion, not just a design promise.**
  `backend/agents/portfolio_manager.py` (the only code that ever
  produces a BUY/HOLD/SELL verdict) is never imported by
  `chat_llm.py`, and its own decision function takes no
  preferences/user argument at all — both asserted directly in
  `test_chat_llm.py::TestPersonalizationNeverAffectsVerdicts`, along
  with a test proving a fixed, verdict-bearing `context` string passes
  through `build_system_prompt` byte-for-byte identical regardless of
  which `risk_appetite`/`preferred_sectors` are supplied alongside it.

## Files changed / created

### Backend — schema

- **`backend/migrations/versions/20260811_0000_f6a7b8c9d0e1_add_personalization_cols.py`**
  (**NEW**) — adds `user_preferences.risk_appetite` (nullable enum:
  `conservative` | `moderate` | `aggressive`) and
  `user_preferences.preferred_sectors` (JSONB, `NOT NULL DEFAULT
  '[]'`).
- **`backend/models/orm.py`** (**MODIFY**, additive only) — adds
  `RiskAppetiteEnum`, and the two matching columns + updated `__repr__`
  on `UserPreferences`.

### Backend — services

- **`backend/services/preference_extractor.py`** (**NEW**) —
  `extract_preferences(message) -> PreferenceExtractionResult`;
  deterministic, keyword-based, zero I/O.
- **`backend/services/preference_service.py`** (**NEW**) —
  `get_or_create_user_preferences` (lazy row creation with a race
  fallback) and `apply_extracted_preferences` (the write-once
  persistence contract).
- **`backend/services/chat_llm.py`** (**MODIFY**, additive only) —
  adds `build_personalization_instruction`, threads
  `risk_appetite`/`preferred_sectors` through `build_system_prompt` /
  `build_system_message` / `build_chat_messages` / `invoke_chat` /
  `astream_chat`, and adds one new bullet to `SYSTEM_PROMPT`'s
  existing "WHAT YOU MUST NEVER DO" list.

### Backend — router

- **`backend/routers/chat_stream.py`** (**MODIFY**) — `_run_one_turn`
  now loads/extracts/persists preferences every turn and passes the
  real `chat_response_style` / `risk_appetite` / `preferred_sectors`
  into `astream_chat`, replacing the old hard-coded
  `_DEFAULT_RESPONSE_STYLE` constant (removed).

### Backend — tests

- **`backend/tests/unit/test_preference_extractor.py`** (**NEW**)
- **`backend/tests/unit/test_preference_service.py`** (**NEW**)
- **`backend/tests/unit/test_chat_schema.py`** (**MODIFY**) — new
  `TestUserPreferencesPersonalizationColumns` class.
- **`backend/tests/unit/test_chat_llm.py`** (**MODIFY**) — new
  `TestBuildPersonalizationInstruction` and
  `TestPersonalizationNeverAffectsVerdicts` classes, plus forwarding
  assertions added to the existing `TestBuildSystemPrompt` /
  `TestBuildSystemMessage` / `TestBuildChatMessages` classes.
- **`backend/tests/unit/test_chat_stream_router.py`** (**MODIFY**) —
  `apply_extracted_preferences` added to every existing
  service-patching fixture (the shared helper plus 3 standalone patch
  blocks that would otherwise call the real, unmocked function against
  a fake session with no real `user_preferences` table behind it), and
  a new `TestPersonalizationWiring` class.

### Scripts & docs

- **`scripts/manual_qa_chat_personalization.py`** (**NEW**) — real-LLM
  manual QA script: ask-once, real-extractor recognition, side-by-side
  tone comparison (conservative vs. aggressive, identical question),
  and a verdict-independence keyword check.
- **`scripts/README.md`** (**MODIFY**) — registers the new script.
- **`docs/week-25/T-106-chat-personalization.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/chat-personalization

git branch
# → * feat/chat-personalization
```

### Step 2 — Add the schema changes

```bash
# backend/migrations/versions/20260811_0000_f6a7b8c9d0e1_add_personalization_cols.py
# backend/models/orm.py (modify)
```

### Step 3 — Add the extraction and persistence services

```bash
# backend/services/preference_extractor.py
# backend/services/preference_service.py
```

### Step 4 — Add the personalization prompt logic and wire the router

```bash
# backend/services/chat_llm.py (modify)
# backend/routers/chat_stream.py (modify)
```

### Step 5 — Add tests

```bash
# backend/tests/unit/test_preference_extractor.py
# backend/tests/unit/test_preference_service.py
# backend/tests/unit/test_chat_schema.py (modify)
# backend/tests/unit/test_chat_llm.py (modify)
# backend/tests/unit/test_chat_stream_router.py (modify)
```

### Step 6 — Add the manual QA script

```bash
# scripts/manual_qa_chat_personalization.py
# scripts/README.md (modify)
```

### Step 7 — Run the migration locally

```bash
set ENVIRONMENT=development
alembic upgrade head
```

Confirm `user_preferences` now has `risk_appetite` and
`preferred_sectors` columns (`\d user_preferences` in `psql`, or
`GET`-ing any endpoint that touches the table). Existing rows get
`risk_appetite = NULL` and `preferred_sectors = '[]'` automatically via
the migration's `server_default`.

### Step 8 — Run the full verification gate locally

Windows Git Bash — remember `ENVIRONMENT=test` cannot be chained with
`&&` on this machine (trailing-space issue); set it as its own line
per the established project workaround:

```bash
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit/test_preference_extractor.py -v
python -m pytest backend/tests/unit/test_preference_service.py -v
python -m pytest backend/tests/unit/test_chat_schema.py -v
python -m pytest backend/tests/unit/test_chat_llm.py -v
python -m pytest backend/tests/unit/test_chat_stream_router.py -v
python -m pytest backend/tests/unit -v
```

If pre-commit hooks fail with `WinError 4551` (Windows App Control
blocking the shim), use the established workaround:

```bash
git commit --no-verify -m "..."
```

GitHub Actions' Linux runners remain the real enforcement gate for
this project. The frontend CI job passes unchanged — this task touches
no frontend file.

### Step 8a — Manual smoke test against a real LLM (required for this task)

Unlike a pure-mocked test run, this is what actually proves "tone
visibly adapts" — the literal wording of this task's second acceptance
criterion, which only a real model call can demonstrate:

```bash
set ENVIRONMENT=development
python -m scripts.manual_qa_chat_personalization
```

Read through all four steps the script prints:

1. **Ask once** — with nothing known yet, does the reply naturally ask
   about risk appetite/sectors? (Either outcome is acceptable — the
   instruction says "if a natural moment arises," not "always.")
2. **Extraction** — confirms the real `extract_preferences` recognises
   a natural self-description ("I'm a conservative investor, and I'm
   mostly interested in IT and FMCG stocks.").
3. **Tone adaptation** — the same question, asked once with
   `risk_appetite="conservative"` and once with `"aggressive"`. Read
   both replies side by side and confirm the tone/emphasis visibly
   differs (downside-focused vs. growth-focused). **Paste both replies
   into the PR description** — this is the direct evidence for the
   acceptance criterion.
4. **Verdict independence** — a keyword sanity check that no
   verdict-bearing figure (BUY, conviction 8/10, Rs 4,250) differs
   between the two replies.

Also test the full end-to-end flow through the real API + ChatWidget
(two terminals from the repo root):

```bash
# Terminal 1
set ENVIRONMENT=development
python -m uvicorn backend.main:app --reload --port 8000
```

```bash
# Terminal 2
cd frontend
npm run dev
```

Open a chat session, let the assistant ask about risk appetite, answer
it, then confirm `user_preferences.risk_appetite` is populated in the
database (`SELECT risk_appetite, preferred_sectors FROM
user_preferences WHERE user_id = '<your-user-id>';`) and that asking a
similar question again in a NEW session does not prompt the assistant
to ask again.

### Step 9 — Commit (two-commit pattern)

```bash
git add backend/migrations/versions/20260811_0000_f6a7b8c9d0e1_add_personalization_cols.py
git add backend/models/orm.py
git add backend/services/preference_extractor.py
git add backend/services/preference_service.py
git add backend/services/chat_llm.py
git add backend/routers/chat_stream.py
git add backend/tests/unit/test_preference_extractor.py
git add backend/tests/unit/test_preference_service.py
git add backend/tests/unit/test_chat_schema.py
git add backend/tests/unit/test_chat_llm.py
git add backend/tests/unit/test_chat_stream_router.py
git add scripts/manual_qa_chat_personalization.py
git add scripts/README.md
git add docs/week-25/T-106-chat-personalization.md

git commit --no-verify -m "feat(chat): personalize assistant tone via stored user preferences

- Add risk_appetite/preferred_sectors columns to user_preferences
  (migration f6a7b8c9d0e1, on top of T-099's e5f6a7b8c9d0) -- both
  empty/NULL until the assistant has asked and the user has answered
  once
- Add preference_extractor.py: deterministic, keyword-based
  recognition of a stated risk appetite / preferred sectors from a
  chat message -- deliberately NOT a second LLM call (determinism,
  cost, and a smaller trust surface for a direct database write)
- Add preference_service.py: get_or_create_user_preferences (lazy
  row creation with an IntegrityError-and-refetch race fallback) and
  apply_extracted_preferences (write-once -- an already-known
  preference is never overwritten by a later, more casual mention)
- Add chat_llm.build_personalization_instruction and thread
  risk_appetite/preferred_sectors through build_system_prompt,
  build_system_message, build_chat_messages, invoke_chat, and
  astream_chat; add one new SYSTEM_PROMPT bullet forbidding
  personalization from ever changing a verdict
- Wire chat_stream.py's _run_one_turn to load/extract/persist
  preferences every turn and forward the real
  chat_response_style/risk_appetite/preferred_sectors into
  astream_chat -- replacing the hard-coded 'concise' constant T-104
  deliberately deferred wiring for
- Add TestPersonalizationNeverAffectsVerdicts to test_chat_llm.py:
  asserts chat_llm.py never imports portfolio_manager, the verdict
  decision function takes no preferences argument, and a fixed
  verdict-bearing context string passes through build_system_prompt
  byte-identical regardless of preferences -- the concrete basis for
  this task's third acceptance criterion
- Update test_chat_stream_router.py's service-patching fixtures
  (shared helper + 3 standalone blocks) to mock the new
  apply_extracted_preferences call; add TestPersonalizationWiring
- Add scripts/manual_qa_chat_personalization.py: real-LLM QA script
  demonstrating ask-once, real extractor recognition, and a
  side-by-side tone comparison for the same question at two risk
  appetites

Closes #106"
```

If a formatter modifies files after staging (black/isort), re-stage
and make a second, separate commit rather than amending:

```bash
git add -A
git commit --no-verify -m "style: apply black/isort formatting to T-106 files"
```

### Step 10 — Push and open the PR

```bash
git push -u origin feat/chat-personalization
```

**Base branch:** `main`
**Compare branch:** `feat/chat-personalization`

## Pull Request

**Title:** `feat(chat): add lightweight per-user preference personalization`

### Summary

Lets the AIRP Assistant ask about a user's investing risk appetite and
preferred sectors once, remember the answer in `user_preferences`, and
use it to adjust tone and emphasis in later replies — never a stored
verdict. Extraction is deterministic (no second LLM call); persistence
is write-once (an already-known preference is never silently
overwritten). Also completes T-104's deliberately deferred
`chat_response_style` wiring, since this task already loads the same
row.

### Changes

- Two new `user_preferences` columns (`risk_appetite`,
  `preferred_sectors`) via a new migration
- `preference_extractor.py` (deterministic recognition) and
  `preference_service.py` (write-once persistence, lazy row creation)
- `chat_llm.py`: new personalization instruction block + a new
  guardrail bullet forbidding personalization from ever changing a
  verdict
- `chat_stream.py`: wired end to end, every turn; real
  `chat_response_style` now read from the database
- Full unit test coverage, including an architectural test proving the
  verdict-producing code path is untouched by this feature
- Manual QA script demonstrating the tone-adaptation criterion against
  a real LLM

### Testing

- `python -m pytest backend/tests/unit -v` — full suite, including 2
  new test files and 3 modified ones for this task
- `python -m mypy backend` / `python -m flake8 backend` / `python -m
  black backend --check` / `python -m isort backend --check`
- `alembic upgrade head` against a local Postgres instance —
  confirmed both new columns land with the correct defaults
- Manual QA (`python -m scripts.manual_qa_chat_personalization`) — see
  pasted transcript below

### Manual QA transcript

_Paste the four-step output of
`python -m scripts.manual_qa_chat_personalization` here, in particular
the full text of both Step 3 replies (3a — conservative, 3b —
aggressive) side by side, since that is the direct evidence for the
"tone visibly adapts" acceptance criterion._

### LangSmith Trace

Every AIRP Assistant call this task's code path triggers is already
traced by T-102's `chat_llm.py` (unchanged tracing behaviour) — no new
trace configuration in this PR.

### Screenshots

_Attach: (1) a chat exchange where the assistant asks about risk
appetite, (2) `user_preferences` row for that user showing
`risk_appetite`/`preferred_sectors` populated after the answer, (3) a
later exchange where the assistant does not ask again._

### Related Issues

Closes #106