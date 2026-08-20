# T-074 — Pre-Deploy Full-System Audit

**Branch:** `feat/claude-changes`
**Status:** DRAFT — awaiting review before any code changes.
**Scope:** Part A/B verification pass per `AIRP-Claude-Code-Full-Audit-Prompt.md`, plus confirmation/correction of every Part C claim.

This document is the required stop-point: **no code has been modified yet.** Everything below is inventory only.

---

## How to read this

- Findings are numbered `F-<n>` and independent of the prompt's `C-<n>` numbering. Each `F` finding notes which `C` item (if any) it confirms, corrects, or supersedes.
- Severity: Blocker / High / Medium / Low, per project convention.
- "Confirmed" = independently verified in the current `main`/`feat/claude-changes` source by direct file read. "Disputed" = my reading disagrees with the prompt's claim, with evidence.

---

## Part 1 — Confirmation/correction of Part C claims

| C# | Prompt's claim | Verdict | Notes |
|----|----|----|----|
| C1 | WS base URL hardcoded to `window.location.host`, no `VITE_WS_BASE_URL` anywhere | **CONFIRMED**, and worse than stated | See F1. `nginx.conf.template` also lacks WS upgrade headers on the chat path — a second break even if C1 is fixed for the compose/nginx deployment shape. |
| C2 | `backend/Dockerfile` CMD is exec-form JSON with hardcoded `--port 8000` | **DISPUTED — as literally described, but real bug underneath.** Current `CMD` is `["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]` — exec form, confirmed. But the *actual* risk C2 describes (Render's `$PORT` never reaching uvicorn) is real regardless of exec vs. shell form, since exec-form arrays never expand env vars. Fix as specified. | See F2. |
| C3 | `render.yaml` does not exist | **CONFIRMED.** No file anywhere in repo. | See F3. |
| C4 | `sentence-transformers`/`torch` pulled in, `chroma_client.py` imports eagerly at module top level (~line 53) | **CONFIRMED.** Import is at `backend/db/chroma_client.py:53` (formerly reported as line 42/53 depending on which agent counted docstring lines — actual live import statement is at line 53), top-level, unconditional. | See F4. |
| C5 | Chroma has no prod backing service, `HttpClient(host=chroma_host, port=chroma_port)` defaults to `localhost:8001` | **CONFIRMED.** `backend/config.py` defaults `chroma_host="localhost"`, `chroma_port=8001`; `get_chroma_client()` in `ENVIRONMENT=production` routes to `HttpClient` with those defaults. | See F4/F5. |
| C6 | `frontend/.env.example` sets `VITE_API_BASE_URL`/`VITE_AUTH_BASE_URL` to bare origins, contradicting its own "leave unset" comment, breaking local dev because `env.ts` fallback appends `/api/v1`/`/auth` | **CONFIRMED**, exact quotes verified in both files. | See F6. |
| C7 | `airp_access_token` cookie `samesite="lax"` unconditionally, breaks cross-site Vercel↔Render | **DISPUTED — partially.** Current code (`backend/routers/auth.py`, `_set_access_token_cookie`) already sets `secure=settings.is_production` (environment-conditional) but `samesite="lax"` is indeed hardcoded, not environment-conditional — so the cross-site failure mode C7 describes is real. **Additional finding beyond C7**: this cookie is currently **not read by any auth dependency** — `get_current_user` only reads the `Authorization` header, never `request.cookies`. So today the cookie is inert either way; fixing `samesite` is still correct to do (per instructions) since the module's own docstring claims it's meant to enable refresh-free session restore, but the *functional* impact is currently zero until something consumes it. No `/auth/refresh` endpoint exists — confirmed, matches C7's separate note. | See F7. |
| C8 | `from __future__ import annotations` in `llm_factory.py:20` and `portfolio_manager.py:65` | **CONFIRMED, but the blast radius is much larger than C8 states.** The rule is violated in at least 10 production files, not 2 — see F8. This changes the fix from "delete two lines" to "delete N lines + add an enforcement check," per C8's own request for a permanent guard. |
| C9 | `max_concurrent_analyses`, `feature_rate_limiting`, `feature_pdf_enabled`, `feature_debate_enabled`, `cache_ttl_fundamentals`, `clerk_*`, `redis_token` are dead/unwired | **MOSTLY CONFIRMED, two corrections.** `feature_pdf_enabled` is **actually used** (`pdf_export.py` reads it to gate PDF rendering) — C9 incorrectly lists it as dead-or-no-op; it works as a flag today. `redis_token` is **actually used** (`db/redis_client.py` reads it as the Upstash TLS password). The rest (`max_concurrent_analyses`, `feature_rate_limiting`, `feature_debate_enabled`, `cache_ttl_fundamentals`, `clerk_secret_key`, `clerk_publishable_key`, `clerk_jwt_issuer`) are confirmed dead. See F9. |
| C10 | `.env.example` stale: `GROQ_MODEL=llama3-70b-8192`, `ANTHROPIC_MODEL=claude-sonnet-4-20250514`, fictional `VITE_API_URL`/`VITE_CLERK_PUBLISHABLE_KEY`/`VITE_APP_NAME`/`VITE_ANALYSIS_TIMEOUT_MS`, missing `CHROMA_PERSIST_DIR`/`MAX_UPLOAD_SIZE_MB` | **CONFIRMED** on every point, exact quotes verified against `config.py` defaults (`anthropic_model="claude-haiku-4-5-20251001"`, `groq_model="llama-3.3-70b-versatile"`). | See F10. |
| C11 | No production guard on default `SECRET_KEY` | **CONFIRMED.** `secret_key` defaults to `"insecure-default-change-in-production"`, no `model_validator` rejects it under `is_production`. Fails **open**, unlike `ACCURACY_SERVICE_TOKEN` which correctly fails closed. | See F11. |
| C12 | Inconsistent `__init__.py` presence | **CONFIRMED**, exact file list verified. | See F12. |
| C13 | `[tool.isort] known_first_party` stale, lists bare names never imported that way | **CONFIRMED**, current list is `["agents","graph","routers","models","services","tools","db","dependencies"]`; every import in the codebase uses `backend.*` prefix. Additionally missing `evals`/`migrations`/`tests` even under the old (wrong) convention. | See F13. |
| C14 | CI never builds Docker images | **CONFIRMED.** `ci.yml` has exactly 3 jobs: `backend`, `frontend`, `ci-pass`. No docker build step anywhere. | See F14. |
| C15 | `mypy` invocation drops `--warn-unused-ignores` | **CONFIRMED.** Not set in `[tool.mypy]` in `pyproject.toml`. | See F15. |
| C16 | Dependency hygiene: `python-jose` CVEs, `PyPDF2` deprecated + `pdfminer.six` redundancy, `requests`/`aiohttp` patch levels, no `bandit` | **RESOLVED — decisions below.** | See F16. |
| C17 | `print()` in `chroma_client.py:40` inside docstring, not live code | **CONFIRMED. Non-issue as originally suspected** — it's inside the module docstring's usage example, not executable code. No fix needed. | Close as non-bug. |

---

## Part 2 — New findings not called out in Part C

These surfaced during the read-through and are real defects the prompt's list didn't anticipate.

### F-A (Blocker) — Portfolio Manager's LangGraph node entry point has no exception guard
`backend/agents/portfolio_manager.py`, `run_portfolio_manager_decision` (~lines 903–917) calls `_run_portfolio_manager_core(...)` with **no surrounding `try/except`**, unlike all 7 other agents' node entry functions. The module's own docstring claims "Never raises," but that claim isn't structurally enforced at the one point that matters most — if `InvestmentDecision(...)` Pydantic construction raises for any reason, the exception propagates uncaught through the very last computational node, aborting the pipeline after every other agent (and up to 2 debate rounds) has already run and been paid for.
**Fix:** Wrap the core call in `try/except Exception`, matching every sibling agent's pattern, degrading to a minimal `HOLD`/conviction=1 decision on failure.
**Why this matters for Part C:** this is exactly the "never raises" contract the project's own Part 0 rules mandate, and it's broken in the single highest-consequence agent.

### F-B (High) — `MAX_DEBATE_ROUNDS` hardcoded in `routing.py`, `settings.debate_rounds` has zero effect
`backend/graph/routing.py:140` defines `MAX_DEBATE_ROUNDS: int = 2` as an independent module constant; `backend/config.py:157` defines `debate_rounds: int = 2` as a documented, presumably operator-tunable feature flag. Nothing in `routing.py` or `nodes.py` ever reads `settings.debate_rounds`. They agree today by coincidence. Setting `DEBATE_ROUNDS=3` in the environment does nothing. Same story for `feature_debate_enabled` (C9's list) — it's declared but the debate loop always runs unconditionally.
**Fix:** Single source of truth — either have `routing.py` read `settings.debate_rounds`/`settings.feature_debate_enabled` at call time, or delete the config fields and stop documenting them as operator-tunable. Also fix the stale ORM column comment in `backend/models/orm.py:387` ("max = settings.debate_rounds") which currently documents a lie.
**Note:** per Part E rule 5, this touches debate-loop *behavior*, not verdict/score calibration — the round count is an orchestration parameter, not a scoring weight. I believe this is safe to fix without triggering the "stop and ask" rule, but flagging explicitly since it's adjacent to debate logic. **I will hold off touching this until you confirm**, since it's arguably debate-loop behavior.

### F-C (Medium) — Unicode box-drawing section comments violate Part 0's ASCII rule
Two files use `# ── Section ──` Unicode dividers instead of the mandated plain ASCII `# ---`:
- `backend/config.py` — 12 occurrences (lines ~42, 53, 74, 83, 94, 102, 119, 143, 155, 179, 198, 244)
- `backend/agents/output_models.py` — throughout the file (every section divider)

Every other file in `backend/graph/` and `backend/agents/` correctly uses ASCII. These two are the outliers.
**Fix:** Replace with ASCII `# --- Section ---`.

### F-D (Medium) — Contrarian's ticker-missing early return resets `debate_round_count` to 0 instead of incrementing
`backend/agents/contrarian_investor.py:713-728` — every other exit path increments `debate_round_count`; this one path (reached only if `ticker` is somehow empty when contrarian runs, which the Planner should prevent) returns `0`. Low risk today (Planner gates this upstream) but a latent inconsistency defensive coding should close.
**Fix:** Increment consistently on this path too.

### F-E (Medium) — nginx production image has no WebSocket upgrade headers for the chat stream path
`frontend/nginx.conf.template` gives `location /api/v1/analysis/` the `Upgrade`/`Connection: upgrade` headers needed for a WS handshake, but the general `/api/` block that would catch `/api/v1/chat/{session_id}/stream` does not. In the Docker Compose / nginx-served deployment shape, chat WebSocket streaming would fail to upgrade even after C1/F1 is fixed.
**Fix:** Add a dedicated `location /api/v1/chat/` block mirroring the analysis one, or generalize with a `map $http_upgrade $connection_upgrade` pattern.

### F-F (Medium) — `secret_key` fails open, `db/session.py` and `models/orm.py` also carry the banned future-import (see F8 expansion)
Covered in the Part 1 table (C11/C8 corrections) — restated here because F8's real file list is materially different from what C8 claimed, and the highest-blast-radius offender (`db/session.py`, imported by literally every router/service) wasn't in the prompt's list at all.

### F-G (Low) — Stale "12 nodes" text in `graph_visualisation.py`'s Markdown template
`backend/graph/graph_visualisation.py` (~line 125) hardcodes "All 12 nodes" in prose while `graph.py` itself documents and logs 15 nodes. Cosmetic — the generated `docs/GRAPH_DIAGRAM.md` would contradict its own dynamically-computed node count section.
**Fix:** Update to 15, or interpolate `{node_count}` so it can't drift again.

### F-H (Low) — Chat "403 vs 404" — Part B's expectation vs. actual (intentional) design
Part B4 asks to verify "chat asking about an analysis the user does not own returns 403, not data." The actual behavior returns **404**, not 403, and this is **consistent and deliberate** across the entire codebase (analysis, chat, document routes all collapse "not found" and "not yours" into 404 specifically to avoid leaking job_id/session_id validity to non-owners — documented in `services/analysis.py`). This is arguably a *better* security posture than 403 (no enumeration oracle), not a bug. Flagging for your call: keep as-is (recommended) or change to 403 for spec-literal compliance.

### F-I (Low) — `bandit` absent from `requirements-dev.txt`; no security-scan CI step
Confirmed absent, ties into C16 and T-079's stated acceptance criterion.

---

## Part 3 — Subsystem verification matrix (Part B) — condensed pass/fail

| Subsystem | Result |
|---|---|
| B1. Agents — deterministic scoring, LLM narrative-only | **PASS**, no LLM output feeds a scoring/verdict decision anywhere. |
| B1. Agents — external-data failure paths degrade, never raise | **PASS for 7 of 8 agents.** Portfolio Manager is the exception — see F-A. |
| B1. `data_quality='insufficient'` propagation (Risk Officer, PM weighting/Gate 2) | **PASS**, correctly implemented and consistently applied. |
| B1. Sector-aware WACC + fallback | **PASS**, `_resolve_sector_key` priority chain confirmed, `diversified`/12% fallback confirmed. |
| B1. `years_available` reaches memo/PM | **PASS for memo.** Reaches `memo_generator`/`analysis` schemas. **Not consulted** by Risk Officer/PM weighting logic (separate from `data_quality`) — flagged as Low/F-9 in agent-audit, likely intentional design, confirming with you rather than assuming. |
| B2. 4 research agents genuinely parallel (Send API) | **PASS**, confirmed via `route_after_planner` returning `list[Send(...)]`. |
| B2. `error_handler`/`sentiment_escalation` routing reachable | **PASS**, both wired and reachable. |
| B2. `debate_loop` terminates at `settings.debate_rounds`, no infinite cycle incl. `None` returns | **FAIL — see F-B.** Terminates correctly at a hardcoded `2`, but not actually driven by `settings.debate_rounds` as documented. No infinite-loop risk found. |
| B2. State persists to Postgres after every node, resumption works | **PARTIAL — new finding, added during Part B.** Persistence-after-every-sequential-node is confirmed sound. But `load_state()`/`StatePersistenceService.load()` — the actual resume-from-snapshot API — is fully implemented and unit-tested in isolation (`test_state_persistence.py::TestResumption`), yet **nothing in the application ever calls it**. `services/analysis.py::run_analysis_pipeline` always builds a fresh `make_initial_state(...)` and there is no router endpoint or retry path that resumes a failed/interrupted job from its last snapshot (confirmed via repo-wide grep for `load_state`/`.load(` call sites and for `resume`/`retry` in `routers/`). So "resumption from a partial snapshot works" is true only at the persistence-layer unit level — there is no working end-to-end resume feature today. Building that resume-trigger flow (a retry endpoint, wiring `load_state` into `run_analysis_pipeline`) would be new product functionality, which Part 0's preamble explicitly puts out of scope for this pass — flagging as a **Medium**, product-decision item for a future task rather than fixing it here. |
| B2. `NODE_*` constants match `pipelineTopology.ts` | **Not yet cross-checked against frontend** — backend list captured (15 constants, see backend-audit agent's report); frontend comparison is a follow-up action item before T-075. |
| B3. WS events emitted in order for every node | **PASS.** |
| B3. `ws_broadcaster` in-process threading contract holds under `ThreadPoolExecutor` | **PASS**, correctly uses `threading.Lock`, justified in docstring. |
| B3. Client disconnect mid-analysis doesn't kill background task | **PASS**, confirmed `BackgroundTasks.add_task` is independent of the WS connection. |
| B3. Malformed/duplicate WS events degrade gracefully | Not independently exercised in this read pass (frontend `isAgentStreamEvent` guard exists per prompt's own claim in C1 context) — recommend a unit test if one doesn't already exist. |
| B4. Chat session/memo-context/tool-calling/REST/WS | **PASS**, with one **self-documented scope gap**: portfolio-wide tools (`get_user_analyses`, `get_memo_by_ticker`, `search_uploaded_documents`) exist but are not bound into the WS streaming call yet (`chat_stream.py` docstring admits this). Not a regression — pre-existing known limitation. |
| B4. Preference extraction round-trip | **PASS**, full write→read loop confirmed correct. |
| B4. Streaming cancellation/reconnection | **PASS**, partial replies persisted on disconnect. |
| B4. Cross-user chat access control | **PASS but returns 404, not 403** — see F-H. |
| B5. `record_pending_evaluations` horizon derivation | **PASS.** |
| B5. `run_due_evaluations` ±5% dead-zone incl. boundary | **PASS**, open-interval semantics confirmed consistent, no off-by-one. |
| B5. `/accuracy/summary`, `/accuracy/history` on zero rows | **PASS**, confirmed no 500, `None` returned for percentages. |
| B5. `/accuracy/run` fails closed on empty token | **PASS.** |
| B6. WeasyPrint: long names, missing sections, `None` scores, non-ASCII | **PASS** for missing sections / `None` scores (explicit fallbacks everywhere). Long company names: no truncation, cosmetic overflow risk only (Low, not a crash). Non-ASCII: HTML-escaped + UTF-8 declared, not independently render-tested in this pass — recommend an explicit test with a ₹/en-dash company name in the fix branch. |
| B6. `memo_output_dir` created if absent, download ownership enforced | **PASS**, `mkdir(parents=True, exist_ok=True)` confirmed; ownership check confirmed before file read. |
| B7. Registration/login/JWT/expiry/WS `?token=` | **PASS.** |
| B7. Cross-user 403 on analysis/chat/document routes | **Returns 404 by design, not 403** — same as F-H, consistent everywhere. |
| B8. Frontend loading/error/empty states, React Query invalidation, mobile responsive | **Not exercised in this read-only pass** — requires running the app. Recommend a manual UI pass alongside T-075's live end-to-end run, per Part D's own instruction. |

---

## Part 4 — Full findings table (for the fix branches)

| # | File:Line | Severity | One-line summary |
|---|---|---|---|
| F1 | `useAnalysisStream.ts`/`useChatStream.ts`/`useChatWidget.ts` + callers | Blocker | No `VITE_WS_BASE_URL`, WS dials wrong origin on split-domain deploy (= C1) |
| F2 | `backend/Dockerfile` CMD | Blocker | `$PORT` never expands in exec-form CMD (= C2) |
| F3 | repo root | Blocker | `render.yaml` missing (= C3) |
| F4 | `backend/db/chroma_client.py:53`, `requirements.txt` | Blocker | Eager `sentence-transformers`/`torch` import inflates cold start (= C4) |
| F5 | `backend/db/chroma_client.py` `get_chroma_client()` | Blocker | No Chroma backing service in prod, defaults to `localhost:8001` (= C5) |
| F6 | `frontend/.env.example:5-19` | High | Bare-origin values break local dev, contradict own comments (= C6) |
| F7 | `backend/routers/auth.py` | High | `samesite="lax"` hardcoded, breaks cross-site cookie; no `/auth/refresh` (= C7) |
| F8 | 10 files incl. `db/session.py`, `models/orm.py`, `agents/llm_factory.py`, `agents/portfolio_manager.py`, `services/memo_generator.py`, 4× `tools/*.py` | High | `from __future__ import annotations` in far more files than C8 stated |
| F9 | `backend/config.py` | High | Dead settings: `max_concurrent_analyses`, `feature_rate_limiting`, `feature_debate_enabled`, `cache_ttl_fundamentals`, `clerk_*` (3 fields). `feature_pdf_enabled`/`redis_token` are actually wired — C9 was wrong to list them as dead. |
| F10 | root `.env.example` | High | Stale models, fictional `VITE_*` vars, missing `CHROMA_PERSIST_DIR`/`MAX_UPLOAD_SIZE_MB` (= C10) |
| F11 | `backend/config.py` `secret_key` | High | No production guard on insecure default (= C11) |
| F-A | `backend/agents/portfolio_manager.py:903-917` | Blocker | PM node entry point unguarded, breaks "never raises" contract |
| F-B | `backend/graph/routing.py:140` vs `config.py:157` | High | `MAX_DEBATE_ROUNDS` hardcoded, disconnected from `settings.debate_rounds`/`feature_debate_enabled` — **holding for your confirmation before fixing, adjacent to debate-loop behavior** |
| F12 | 7 `backend/` subdirs | Medium | Inconsistent `__init__.py` presence (= C12) |
| F13 | `pyproject.toml` `[tool.isort]` | Medium | Stale `known_first_party` list (= C13) |
| F14 | `.github/workflows/ci.yml` | Medium | No docker-build CI job (= C14) |
| F15 | `pyproject.toml` `[tool.mypy]` | Medium | Missing `warn_unused_ignores` (= C15) |
| F-C | `config.py`, `output_models.py` | Medium | Unicode box-drawing comments violate ASCII rule |
| F-D | `contrarian_investor.py:713-728` | Medium | `debate_round_count` not incremented on ticker-missing path |
| F-E | `frontend/nginx.conf.template` | Medium | No WS upgrade headers for chat stream path |
| F16 | `requirements.txt`, `requirements-dev.txt` | Low | Dependency hygiene: CVEs, deprecated pkgs, no bandit (= C16, needs dedicated pass) |
| F-G | `backend/graph/graph_visualisation.py:~125` | Low | Stale "12 nodes" text |
| F-H | routers (analysis/chat/document) | Low | 404 vs 403 for cross-user access — recommend keeping 404, confirm with you |
| F-I | `requirements-dev.txt` | Low | No bandit |
| F17 (=C17) | `backend/db/chroma_client.py:40` | — | **Non-issue** — `print()` confirmed inside docstring, not live code. Closing, no fix needed. |

---

## Part 5 — Open questions for you before I start editing

1. **F-B (debate rounds wiring)** — Part E rule 5 says stop and ask before anything that could change agent scoring/verdict behavior. Wiring `MAX_DEBATE_ROUNDS` to `settings.debate_rounds` doesn't change the *number* (both are `2` today) but does make it operator-tunable going forward. OK to fix as a config-hygiene branch, or do you want this deferred/untouched?
2. **F-H (404 vs 403)** — recommend keeping 404 (better security posture, already consistent everywhere). Confirm, or do you want it changed to match the prompt's literal B4/B7 expectation?
3. **C4/C5 decision (RAG/Chroma on Render free tier)** — the prompt asks me to pick (a) lazy import + `FEATURE_RAG_ENABLED` flag, (b) hosted embeddings API, or (c) paid Render tier. My recommendation is **(a)**: lazy-import the embedding function, add `FEATURE_RAG_ENABLED` (default off in production), and confirm News Sentiment already degrades cleanly without RAG (needs a test either way). This is the lowest-risk, zero-new-infra option and keeps the free tier viable. Confirm before I build the branch for C4/C5.
4. **F9 dead settings** — C9 says implement `max_concurrent_analyses` and `feature_rate_limiting`, delete the Clerk fields. Confirmed reading, no objection — will implement both as real gates (a semaphore for concurrency, a basic per-IP/per-user rate limiter for the public routes) unless you'd rather point me at a specific library/approach (e.g. `slowapi`, Redis-backed token bucket via the existing `redis_client.py`).
5. **F8 scope** — since the banned import shows up in ~10 files (not 2), do you want the "add a permanent guard" part of C8 (flake8/pre-commit check) done in the same branch as the deletions, or split into its own `chore/` branch?

---

## Part 6 — Proposed branch plan for Part C fixes (pending your go-ahead)

Following Part E's "one branch per concern" rule:

1. `fix/ws-base-url` — F1/C1 (+ F-E nginx chat WS headers, same concern)
2. `fix/render-port-binding` — F2/C2
3. `chore/render-blueprint` — F3/C3
4. `chore/lazy-rag-embeddings` — F4/F5/C4/C5 (pending your answer to Q3)
5. `fix/frontend-env-example` — F6/C6
6. `fix/cross-site-auth-cookie` — F7/C7
7. `fix/remove-future-annotations` — F8/C8 (+ enforcement guard, pending Q5)
8. `feat/concurrency-and-rate-limiting` — F9/C9 concurrency+rate-limit implementation, + delete Clerk fields
9. `fix/env-example-staleness` — F10/C10 + machine-checked test walking `Settings` fields against `.env.example`
10. `fix/secret-key-prod-guard` — F11/C11
11. `chore/init-py-consistency` — F12/C12
12. `chore/isort-known-first-party` — F13/C13
13. `ci/docker-build-job` — F14/C14
14. `chore/mypy-warn-unused-ignores` — F15/C15
15. `chore/ascii-section-comments` — F-C
16. `fix/contrarian-debate-count` — F-D
17. `fix/portfolio-manager-exception-guard` — F-A
18. `chore/dependency-hygiene` — F16/C16 (bandit + CVE pins)

Each branch gets its own `docs/week-28/T-0XX-*.md` workflow doc, cut from `main`, per Part E rule 2/3. I'll start once you review this document and tell me which findings to proceed on (all of them, a subset, or with the modifications noted in Part 5).

---

## Part 7 — Part B completion log (2026-08-19)

Per your go-ahead, Part B (subsystem verification) is complete. All work stayed on `feat/claude-changes` as instructed — no new branches were cut. Changed files:

- `backend/agents/portfolio_manager.py` — **F-A fix**: wrapped `_run_portfolio_manager_core(...)` in `try/except Exception` in `run_portfolio_manager_decision`, matching every other agent's node-entry-point guard. Degrades to `HOLD`/conviction=1 on any internal failure instead of crashing the whole pipeline at the last node.
- `backend/graph/routing.py` — **F-B fix**: `route_after_contrarian` now reads `settings.debate_rounds` live instead of a hardcoded, disconnected `MAX_DEBATE_ROUNDS` constant. `DEBATE_ROUNDS` env var is now genuinely operator-tunable. `MAX_DEBATE_ROUNDS` is kept as a backward-compatible alias (`= settings.debate_rounds`) for existing imports.
- `backend/agents/contrarian_investor.py` — **F-D fix**: the ticker-missing early-return path now increments `debate_round_count` like every other exit path, instead of resetting it to 0.
- `backend/tests/unit/test_node_constants_frontend_sync.py` — **new file**: genuine cross-language drift test (Part B2's "add a test that fails if [NODE_* constants] ever diverge" requirement). Parses `pipelineTopology.ts`'s actual string literals from the Python side and asserts byte-for-byte equality with `backend/graph/nodes.py`'s NODE_* constants — closes the gap left by the existing frontend-only self-consistency test.
- `backend/tests/unit/test_portfolio_manager.py`, `test_contrarian_investor.py`, `test_debate_loop.py`, `test_pdf_export.py` — regression tests added for F-A, F-D, F-B, and Part B6 (long company names, ₹/en-dash non-ASCII, missing sections — all confirmed rendering without exception).
- `frontend/src/test/useAnalysisStream.test.ts` — added tests for a well-formed-but-wrong-shape WS message and a duplicate-event delivery, closing the last gap in Part B3's "malformed/out-of-order/duplicate events degrade gracefully" requirement (the frontend already had the malformed-JSON case and full pending→running→done + debate-cycle coverage in `liveGraphState.test.ts`).

**New finding surfaced during Part B** (added to Part 3's matrix): `state_persistence.py`'s `load_state()`/resume API is fully implemented and unit-tested in isolation, but **nothing in the running application ever calls it** — `run_analysis_pipeline` always starts fresh via `make_initial_state`, and there is no retry/resume router endpoint. "Resumption works" is true only at the persistence-layer unit level, not as a working end-to-end feature. I did not build a resume-trigger flow since that would be new product functionality, out of scope for Part 0's "no new features" instruction — flagging as a Medium product-decision item for a future task.

**Verification gate — real output, both fully green:**

Backend (`ENVIRONMENT=test`):
```
python -m black backend/         -> All done, 155 files left unchanged
python -m isort backend/ --check-only -> clean (0 exit)
python -m flake8 backend/        -> clean (0 exit)
python -m mypy backend/          -> Found 2 errors in 1 file (backend/routers/chat_stream.py:469,479 -- pre-existing, untouched this session, unrelated to Part B scope)
python -m pytest backend/        -> full suite passes (exit 0); the 2 project-documented flaky
                                     websocket heartbeat tests (test_websocket_router.py::TestHeartbeat,
                                     T-074's own Part 0 calls these out by name) were deselected for this
                                     run, not deleted or modified -- they hang on this machine's timing
                                     but are pre-existing, documented, known-flaky per project rules.
```

Frontend:
```
npm run type-check  -> clean (0 exit)
npm run lint         -> clean (0 exit)
npm run format:check -> "All matched files use Prettier code style!"
npm run test:run     -> 90 test files, 600 tests, all passed
npm run build         -> built in 7.58s (pre-existing >500kB chunk-size warning, not an error, out of scope)
```

**Environment note:** this machine's global Python site-packages was significantly drifted from the repo's pinned versions (a much newer `langchain`/`langgraph`/`chromadb` installed globally from unrelated projects, `mypy`'s compiled extension briefly blocked by an Application Control policy after reinstall). Backend `requirements.txt` and `requirements-dev.txt` were installed to bring the environment back in line with what CI actually pins — this surfaced ~100 test failures that were 100% attributable to the version drift (not code defects), all resolved once the correct versions were installed. Recommend a dedicated virtualenv for this repo going forward to avoid this recurring locally.

None of the 8 Part B tasks required touching the debate-loop scoring/verdict logic itself (F-B only changes which config value the round cap reads from, not the cap's value or any scoring weight), so `test_verdict_calibration_regression.py` was not at risk and was confirmed passing in the full suite run above.

**No code changes were made outside the 8 Part B items listed above** — Part C's branch plan (Part 6) is still awaiting your go-ahead per the open questions in Part 5.

---

**No code has been changed beyond the Part B scope above. Awaiting your direction on Part C.**

---

## Part 8 — C16 dependency hygiene decisions (2026-08-19)

- **`python-jose[cryptography]==3.3.0` (CVE-2024-33663, CVE-2024-33664):** kept as-is, not migrated to `pyjwt`. Both CVEs are inapplicable to how this app actually uses the library: `backend/services/auth.py` pins a single symmetric algorithm (`algorithms=["HS256"]`) at both encode and decode, so CVE-2024-33663 (asymmetric/symmetric algorithm-confusion) has no code path to exploit here — only one algorithm is ever accepted. CVE-2024-33664 is a JWE (encryption) decompression-bomb; this app only ever calls `jwt.encode`/`jwt.decode` for JWS (signing), never JWE, so that code path is never reached either. A full migration to `pyjwt` is still worth doing eventually (python-jose's upstream is largely inactive), but is a security-sensitive auth-module change that deserves its own dedicated branch with focused testing, not a drive-by swap inside an already-large Part C pass — noted here as a recommended follow-up task, not done in this session.
- **`PyPDF2==3.0.1` vs `pdfminer.six==20231228`:** confirmed genuinely both needed, not redundant. `backend/tools/earnings_transcript.py::_extract_text_from_pdf_bytes` (reused by `backend/services/documents.py`) runs pdfminer.six as the primary extractor and falls back to PyPDF2 only when pdfminer returns empty text — an intentional two-library fallback chain, already documented in both modules' docstrings. No change made.
- **`requests==2.31.0` / `aiohttp==3.9.5` patch levels:** not bumped in this session. Verifying exact current CVE-fixed versions requires checking a live vulnerability database, which wasn't available in this environment; bumping blind risks a transitive dependency break with no way to verify the fix actually lands. Recommended as a follow-up: run `pip-audit` or `safety check` against `backend/requirements.txt` in an environment with network access, and bump only what it flags.
- **`bandit` — added.** `backend/requirements-dev.txt` now pins `bandit==1.7.9`; `pyproject.toml`'s new `[tool.bandit]` section skips `B101` (assert-for-narrowing, a deliberate project-wide pattern, not a security check) and excludes `backend/tests`/`backend/migrations`. A `bandit -r backend/ -c pyproject.toml` CI step was added to `.github/workflows/ci.yml`. Every other individual finding bandit raised (2× B105 false-positive "hardcoded password" on a cookie name constant and a sentinel default value that's checked against rather than used as a secret, 1× B107 on a stream-token parameter default, 3× B110 on intentional idempotent `except Exception: pass` cleanup paths) was triaged and marked with an inline `# nosec B1xx` comment plus a one-line reason at its exact location. `bandit -r backend/ -c pyproject.toml` now runs clean (0 issues, 6 explicitly-triaged skips).

---

## Part 9 — Part C completion (2026-08-19)

All 16 items from Part 6's fix plan are done, on `feat/claude-changes` as instructed (no branch-per-concern, per your original instruction to keep everything on this one branch). Summary of what changed, item by item:

| # | Item | What was actually done |
|---|---|---|
| C1/F1 | WS base URL split-origin fix | `VITE_WS_BASE_URL` added to `frontend/src/config/env.ts`/`vite-env.d.ts` with fallback chain (explicit var → derived from absolute `VITE_API_BASE_URL` → `window.location`); both `useAnalysisStream.ts`/`useChatStream.ts` consult it via `env.wsBaseUrl`. `frontend/src/test/env.test.ts` covers the derivation. |
| F-E | nginx chat WS headers | Added a dedicated `location /api/v1/chat/` block to `frontend/nginx.conf.template` with `Upgrade`/`Connection` headers — the general `/api/` block never had them, so chat WS would never actually upgrade through the Compose/nginx image. |
| C2/F2 | Render `$PORT` binding | `backend/Dockerfile`'s `CMD` switched to shell form (`${PORT:-8000}`); `HEALTHCHECK` reads the same `$PORT`. |
| C3/F3 | `render.yaml` | Created at repo root — Docker runtime, `dockerContext: .`, `healthCheckPath: /health`, all 43 env vars cross-checked programmatically against `Settings.model_fields` (only `database_test_url`, intentionally test-only, is absent). |
| C4/C5/F4/F5 | RAG/Chroma production gate | Per my recommendation you didn't object to: lazy-imported `SentenceTransformerEmbeddingFunction` inside `get_embedding_function()`; added `FEATURE_RAG_ENABLED` (defaults off in production via a `model_validator`, respects an explicit override); News Sentiment agent skips both Chroma call sites entirely when off. |
| C6/F6 | `frontend/.env.example` | Both `VITE_API_BASE_URL`/`VITE_AUTH_BASE_URL` lines commented out, matching the file's own "leave unset" guidance; `VITE_WS_BASE_URL` documented alongside. |
| C7/F7 | Cross-site auth cookie | `samesite` is now `"none"` in production / `"lax"` otherwise (paired with the existing `secure=is_production`); tested both branches. No `/auth/refresh` endpoint — still a documented known limitation, out of scope. |
| C8/F8 | Banned `from __future__ import annotations` | Removed from all 10 production files the audit found (not just the 2 the prompt named) — `db/session.py`, `db/chroma_client.py`, `agents/llm_factory.py`, `agents/portfolio_manager.py`, `models/orm.py`, `services/memo_generator.py`, `tools/{financials,macro,news,ratios}.py`. Fixed the resulting genuine forward-reference `NameError`s in `models/orm.py` by quoting just the affected type annotations (`Mapped[list["Analysis"]]` etc.), not by reintroducing the future import. Added `backend/tests/unit/test_no_future_annotations.py` as a permanent, dependency-free enforcement guard (runs on every `pytest` invocation). |
| C9/F9 | Concurrency + rate limiting; delete Clerk | Implemented both as real gates: `reserve_analysis_slot`/`release_analysis_slot` (in-process counter, `MAX_CONCURRENT_ANALYSES`) reject `/analysis/start` with 503 at capacity; new `backend/services/rate_limiter.py` (in-process fixed-window, per-client-IP, `/health` exempt) wired as middleware, gated by `FEATURE_RATE_LIMITING`. Deleted `clerk_secret_key`/`clerk_publishable_key`/`clerk_jwt_issuer` outright (confirmed `feature_pdf_enabled`/`redis_token` were NOT dead, contra C9's claim — left as-is). |
| C10/F10 | `.env.example` staleness | Fixed `GROQ_MODEL`/`ANTHROPIC_MODEL` to match `config.py` defaults, removed the 4 fictional `VITE_*` entries, added `CHROMA_PERSIST_DIR`/`MAX_UPLOAD_SIZE_MB`/`FEATURE_RAG_ENABLED`/`RATE_LIMIT_REQUESTS_PER_MINUTE`, deleted the Clerk block. Added `backend/tests/unit/test_env_example_sync.py` — machine-checks every `Settings` field has a matching line and vice versa. |
| C11/F11 | `SECRET_KEY` production guard | `model_validator` raises at startup if `ENVIRONMENT=production` and `SECRET_KEY` is still the placeholder. `ACCURACY_SERVICE_TOKEN` deliberately NOT given the same hard-fail treatment (documented reasoning: it already fails closed, and an empty value there is an availability concern, not an auth bypass). |
| C12/F12 | Missing `__init__.py` | Added to `agents/`, `graph/`, `tools/`, `services/`, `tests/`, `tests/unit/`, `migrations/`. |
| C13/F13 | Stale isort config | `known_first_party` replaced with `["backend"]` — confirmed a true no-op change (isort's output was already correct; the old list matched nothing real). |
| C14/F14 | CI docker build | Added a `docker` job to `.github/workflows/ci.yml` building both Dockerfiles via buildx with GHA layer caching; added to `ci-pass`'s `needs`. |
| C15/F15 | `mypy warn_unused_ignores` | Added. Surfaced zero unused ignores (all existing ones are legitimate) — the flag itself found nothing to clean up. Also fixed a genuine, pre-existing, unrelated mypy error in `backend/routers/chat_stream.py` (a `MutableMapping` vs `dict` type mismatch) since it was blocking a fully green `mypy backend/` run. |
| F-C | Unicode box-drawing comments | Converted all 12 in `config.py` and all 44 in `agents/output_models.py` to plain ASCII `# --- Section ---`. Left the class-hierarchy tree diagram inside `output_models.py`'s module docstring untouched (decorative documentation, not a code section comment, and doesn't trigger flake8 E501). |
| C16/F16 | Dependency hygiene | `python-jose` CVEs: evaluated as inapplicable to this app's actual usage (single pinned symmetric algorithm, JWS-only) — documented, not migrated; a full `pyjwt` migration is flagged as a follow-up deserving its own branch. `PyPDF2`/`pdfminer.six`: confirmed genuinely both needed (documented primary/fallback chain), no change. `requests`/`aiohttp`: not bumped blind without a live CVE database to verify against — flagged for a `pip-audit`/`safety` follow-up. `bandit` added to `requirements-dev.txt` + CI step (`pyproject.toml`'s `[tool.bandit]`); all 6 real findings triaged with inline `# nosec` comments, 0 issues on a clean run. |

**Verification gate — final run, both fully green, real output:**

Backend (`ENVIRONMENT=test`):
```
python -m black backend/ --check   -> 166 files would be left unchanged
python -m isort backend/ --check-only -> clean (0 exit)
python -m flake8 backend/          -> clean (0 exit)
python -m mypy backend/            -> Success: no issues found in 166 source files
python -m bandit -r backend/ -c pyproject.toml -> 0 issues (6 explicitly-triaged nosec skips)
python -m pytest backend/          -> full suite passes (exit 0); the 2 project-documented
                                       flaky websocket heartbeat tests deselected (not
                                       deleted, not modified), same as the Part B run
```

Frontend:
```
npm run type-check  -> clean (0 exit)
npm run lint         -> clean (0 exit)
npm run format:check -> "All matched files use Prettier code style!"
npm run test:run     -> 91 test files, 607 tests, all passed
npm run build         -> built in 6.86s (pre-existing >500kB chunk-size warning, out of scope)
```

Per Part E rule 5: none of the 16 items changed agent scoring or verdict behaviour (C9's concurrency/rate-limit gates and C4/C5's RAG flag are orchestration/infra concerns, not scoring weights) — `test_verdict_calibration_regression.py` passed in the full suite run above, unchanged.

**All work is on `feat/claude-changes`, ready for your review before any merge to `main`.**

---

## Live end-to-end sweep (2026-08-19/20) — bugs found only by running the real stack

Part A-C above was a static audit plus targeted unit-test fixes. It never actually
booted the `docker-compose` stack against a real Groq key and clicked through the app.
Once a live analysis got stuck at 0% with a persistent "Connection closed unexpectedly
(code 1006)" error, the whole system was run end-to-end (backend + frontend containers,
real browser, real LLM calls) and every major feature exercised by hand: registration/
login, company autocomplete, starting a live analysis, the WebSocket progress stream
(Cards + Graph views, debate transcript), full pipeline completion through PDF export,
the results panel + charts, the AIRP Assistant chat widget, and the public Accuracy
dashboard. Four bugs were found this way that no unit test caught, because each one
only manifests under a condition the unit suite doesn't reproduce (a real worker
thread, a real decommissioned model ID, real StrictMode double-mount timing, a real
reasoning model with no tools bound):

| # | Bug | Root cause | Fix |
|---|-----|------------|-----|
| L1 | Every analysis crashed instantly on Linux/Docker | `backend/graph/node_profiler.py`'s `_make_timeout_ctx` selected `signal.alarm()`-based timeout whenever `_IS_POSIX`, but `backend.services.analysis.run_analysis_pipeline` invokes the graph via `asyncio.to_thread(...)`, i.e. a worker thread — `signal.alarm()` raises `ValueError: signal only works in main thread of the main interpreter` off the main thread. This crashed the very first profiled node of every run. | Added a `threading.current_thread() is threading.main_thread()` check alongside `_IS_POSIX`; falls back to the pre-existing, thread-safe `_ThreadTimeout` otherwise. 5 new tests in `test_node_profiler.py`, including one that spawns a real `threading.Thread` to prove the fix. |
| L2 | Every LLM call 404'd | Groq fully retired `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` from its catalog since Part C's own C10 fix pinned the former. Confirmed live against `GET /openai/v1/models` with a real key. | `groq_model` default changed to `openai/gpt-oss-120b` (`backend/config.py`, `.env.example`, `render.yaml`), the closest available capability tier. |
| L3 | Stuck-at-0%/"Connection closed unexpectedly (code 1006)" — the user's original report | Two compounding bugs: (a) `useAnalysisStream.ts` used one shared `useRef(true)` flag to detect a stale socket; under React 18 StrictMode's dev-only mount→cleanup→mount, the flag got reset by the second effect run before the first (doomed) socket's async `onclose` fired, so its phantom failure overwrote the real, connected socket's state. (b) `websocket.py`'s late-connect replay sent exactly one event even when several pipeline nodes (including the 4-way parallel research fan-out) had already completed, so a client connecting mid-run saw a single stale snapshot instead of the real history. | (a) Replaced the shared flag with `currentSocketRef` compared by object identity per socket instance. (b) `_snapshot_to_events` (renamed from `_snapshot_to_event`) now replays one event per completed node, expanding `research_join` into its 4 constituent agents. New tests in both `useAnalysisStream.test.ts` and `test_websocket_router.py`. |
| L4 | AIRP Assistant chat always replied "failed to generate a response" | `backend/services/chat_llm.py`'s `SYSTEM_PROMPT` told the model it had "tools you are given" / "tools available to you" for portfolio-wide questions, but no code path anywhere in the repo actually calls `.bind_tools(...)` — `backend/tools/portfolio_tools.py` exists but was never wired into `astream_chat`/`invoke_chat`. `openai/gpt-oss-120b` (a reasoning model) took the prompt literally and emitted a tool call; Groq rejected it with `Tool choice is none, but model called a tool` since no `tools` param was ever sent, crashing every chat turn. | Reworded the two prompt passages to describe the assistant's real capability (stored context only) instead of promising live tool access that doesn't exist. Verified live: a follow-up chat turn streamed a normal reply. All 61 `test_chat_llm.py` tests still pass (none asserted the removed phrasing). |

Two more issues were found purely from running the **full** backend suite (not just
targeted files) inside the actual Linux container image (matching the real deploy
target, not the Windows dev host) rather than trusting "no failures in the files I
touched":

| # | Bug | Root cause | Fix |
|---|-----|------------|-----|
| L5 | `test_api_integration_flow.py::test_stream_closes_immediately_once_status_is_terminal` failed | Pre-dated the L3(b) replay fix above — it asserted the *first* replayed event for a terminal job was `is_final: True`, which stopped being true once replay started emitting one event per completed node. | Updated to drain events until `is_final`, matching the already-updated assertions in `test_websocket_router.py`. |
| L6 | `test_config.py`'s two `secret_key`-default tests failed, but only inside the Docker container / CI, never on the Windows host | `_construct_settings`'s `_env_file=None` isolates the test from a `.env` **file**, but pydantic-settings still reads real **OS environment variables** regardless of `_env_file` — and the container has a real `SECRET_KEY` exported for the app's own runtime use, which silently outranked the field's Python default for any test that didn't explicitly override it. | `_construct_settings` now also pops every `Settings` field's env var that isn't part of that call's overrides, restoring each afterward. |

**Final verification after all 6 fixes** — both gates green, run twice (Windows host
and, for the backend, the real Linux container image):

```
Frontend: npx vitest run           -> 91 files, 608 tests, all passed
Backend (Windows host):            individual/targeted files all green
Backend (Linux container, ENVIRONMENT=test):
                                     python -m pytest backend/  -> full suite,
                                     0 failures, exit 0
```

(The Windows-host *full-suite* run was abandoned after two different non-deterministic
hangs at different points in a long sequential run — not reproducible when the same
files were run in isolation or small groups, and not reproducible at all inside the
Linux container. Treated as local Windows-host flakiness — possibly endpoint-security
interference, consistent with the earlier mypy DLL-load block this same environment
hit during Part C — not a code defect; the container run is the more representative
signal anyway since it matches the actual deploy target.)

Live-verified by hand in the browser after the fixes: register → login → start a live
Infosys analysis → real-time progress through all agents (no 1006 error, no stall) →
completed HOLD verdict with results panel + charts → AIRP Assistant chat round-trip →
public Accuracy dashboard. All on `feat/claude-changes`, still unmerged.

### L8/L9 — a second live sweep found the missing-live-event class of bug is
broader than L7, plus one stale UI string

A follow-up live sweep (registering a fresh account, running full analyses end to
end while actually watching, not navigating away) reproduced a variant of the same
symptom L7 fixed, but from a different trigger:

**L8 — an analysis that finished correctly server-side (`status='completed'`,
`last_completed_node='pdf_export'` in PostgreSQL) left a live-connected browser
tab stuck at 89% forever**, with Risk Officer/Contrarian Investor/Valuation Agent
never flipping past "Thinking" and Portfolio Manager stuck at "Waiting" -- this
time with no crash anywhere (every agent's own "never raises" contract held; L7's
fix never even had a reason to fire). Root-caused two ways:

1. A genuine race in `stream_analysis_progress` itself: `subscribe()` to the live
   broadcaster used to run only after the DB round-trip for auth/snapshot AND
   after the full replay had been sent over the wire -- both real, non-trivial
   I/O. Any node that completed and published in that window had nowhere to
   land: too late for the replay (built from an already-fetched, now-stale
   snapshot) and too early for the live subscription (not registered yet).
   Invisible when nodes take real seconds each (the common case), but a run
   where several nodes complete within milliseconds of each other (every LLM
   call failing instantly on the same Groq rate limit, as happened repeatedly
   during this session's own testing) could lose multiple consecutive nodes'
   events this way. **Fix**: `subscribe()` now happens first, before any DB
   work or replay I/O, so there is no window in which a published event has
   nowhere to go. This flips the race the other way -- a node finishing in the
   now-much-narrower gap between `subscribe()` and the snapshot fetch would
   show up in both the live queue and the replay -- so a new
   `_drain_already_replayed` helper discards exactly that overlap, non-blocking,
   right before the main forward loop starts.
2. Even with (1) fixed, a live-tested run (this one genuinely slow --
   `macro_economist`/`sentiment_analyst` each took ~38s against
   `NODE_TIMEOUT_S=30s`, not the instant-failure profile (1) targets) still
   lost exactly the terminal `pdf_export` event and hung at 89% forever. The
   underlying broadcaster mechanism was verified directly, in isolation
   (`subscribe`/`publish_event`/queue delivery), to be correct -- a
   fire-and-forget, at-most-once, `call_soon_threadsafe`-based broadcast has no
   redelivery by design, so a single lost delivery for whatever event happens
   to be in flight can't be fully ruled out by any one timing fix. Rather than
   keep chasing the exact trigger for this specific loss (Groq's quota was
   fully exhausted by this point in the session, blocking further live
   reproduction), this closes the failure mode itself: every heartbeat tick in
   `_forward_live_events` (previously just a generic "still working"
   keep-alive) now also re-checks the job's real PostgreSQL status via a new
   `_catch_up_if_already_terminal` helper. If the job is already terminal but
   this connection was never told, it sends the correct terminal event now and
   closes -- capping the worst-case UI staleness at one heartbeat interval
   (10s by default) instead of forever, regardless of why the original event
   went missing.

**L9** (cosmetic, found in passing): the landing page's tech-stack chip row
(`TechStackSection.tsx`) still said "Groq Llama 3.3" after L2 changed the actual
default model to `openai/gpt-oss-120b` -- stale since the moment L2 landed.
Changed to just "Groq" (the provider, not a specific model), with a comment
explaining why: the model string has already gone stale once from a Groq-side
change outside this codebase's control, and free-tier availability can shift
again without notice.

Both `_drain_already_replayed` and `_catch_up_if_already_terminal` required
threading the authenticated `user_id` into `_forward_live_events` (needed for
the ownership-scoped status re-check) -- a signature change reflected in
`test_websocket_router.py`'s two heartbeat tests. Verified: `mypy`/`flake8`
clean on every changed file, and the full backend suite (91 files) passes with
zero failures inside the Linux container both before and after this second
sweep's fixes. Frontend: 608/608 both times.

A false lead worth recording so it isn't re-chased: mid-investigation, the
company autocomplete on the "New analysis" page appeared to silently fail to
register a selection across three different interaction methods (click,
click-by-DOM-ref, keyboard Enter) in the automated browser tool, each attempt
showing the plain typed text with a "Select a company from the list" validation
error. Direct DOM inspection via injected JavaScript proved the real page state
was correct the whole time (`input.value === "Infosys (INFY)"`,
`aria-expanded="false"`, no listbox) -- the tool's own screenshot/accessibility-
tree snapshots were simply stale by a render or two. Not a product bug.

### L7 — the actual remaining root cause of the user's repeated live "stuck at X%,
Connection closed unexpectedly (code 1006)" reports, found on a second live run

The four L1-L4 fixes above were necessary but not sufficient. A later live run
(started fresh after L1-L6 landed) genuinely stalled again -- this time proven, via
`docker logs`, to be a **real backend crash**, not a frontend rendering bug: Groq's
free-tier **daily** token quota (`tokens per day (TPD): Limit 200000`) was fully
exhausted by the day's extensive live testing, every agent's LLM call started
failing with 429, and eventually one call escaped every individual agent's own
documented "never raises" contract (each of `risk_officer.py`, `contrarian_investor.py`,
`portfolio_manager.py`, etc. gracefully degrades to fallback content on its own LLM
failures -- confirmed by reading each one's `except Exception` handler) and reached
`run_analysis_pipeline`'s own outer `except Exception` in
`backend/services/analysis.py`.

That handler already did the right thing for `GET /status` and the dashboard: it
called `StatePersistenceService.mark_failed(...)`, writing `status='failed'` to
PostgreSQL. What it never did was tell anyone **watching live** over
`WS /api/v1/analysis/{job_id}/stream` -- `backend.graph.nodes._run_broadcast`, the
only code path that calls `ws_broadcaster.publish_event(...)`, only ever runs from a
node's own successful return. A crash that skips straight to
`run_analysis_pipeline`'s except block therefore updated the database but left every
live WebSocket subscriber's `_forward_live_events` loop waiting forever for an
`is_final` event that was never coming -- until the connection eventually died of an
unrelated timeout, surfacing to the browser as exactly the ambiguous "Connection
closed unexpectedly (code 1006)" the user kept reporting, at whatever progress
percentage the last *successful* node happened to reach first.

**Fix**: `run_analysis_pipeline`'s except block (`backend/services/analysis.py`) now
also publishes a terminal `AgentStreamEvent` (`is_final=True`, `status="failed"`) via
`ws_broadcaster.publish_event` -- the same broadcaster `_run_broadcast` uses for
every normal node completion -- immediately after `mark_failed`, wrapped in its own
`try`/`except` so a broadcaster bug can never make this already-in-an-except-block
cleanup path raise. Two new regression tests in `test_analysis_service.py`
(`test_broadcasts_a_final_failed_event_when_graph_raises`,
`test_never_raises_when_broadcast_itself_raises`) cover the fix and its own
failure-safety. Verified: `backend/services/analysis.py` type-checks clean
(`mypy`), lints clean (`flake8`), and the full backend suite (91 files / all tests)
passes with zero failures inside the Linux container after this change.

Live re-verification of this specific fix was not completed against a real Groq
call -- the day's TPD quota was still exhausted at the time of the fix, and forcing
another real 429 to confirm the browser now shows "This analysis did not complete"
instead of hanging would have required either waiting out Groq's multi-hour quota
reset or a paid tier upgrade, neither of which is this session's call to make. The
regression tests assert the exact mechanism (the correct event is published with the
correct shape) that `backend.routers.websocket._forward_live_events` and
`frontend/src/hooks/useAnalysisStream.ts` already have their own passing test
coverage for consuming correctly.
