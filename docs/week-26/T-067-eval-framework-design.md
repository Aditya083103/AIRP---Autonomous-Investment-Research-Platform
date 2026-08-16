# T-067 — Design LangSmith Eval Framework

**Phase:** 11 — Evaluation
**Week:** 26
**Branch:** `feat/eval-framework-design`
**Type:** Planning
**Priority:** 🔴 Critical
**Est. hours:** 3

## Summary

T-067 is the design pass for AIRP's LangSmith evaluation framework. It
defines, for each of the five criteria in the task description —
fundamental accuracy, sentiment direction, contrarian novelty, memo
completeness, and latency <90s — exactly what dataset each eval needs, what
the pass/fail rubric is, and what grading scale feeds into T-072's
`EVALUATION.md`. It is a **docs-only** task: no agent code, no evaluator
code, no test files. T-068–T-071 build against this design in later PRs.

## Acceptance criteria (from task spec)

- [x] `docs/EVALUATION.md` written with criteria, rubrics, and grading scale
      for each agent

  **Naming deviation, called out explicitly:** `docs/EVALUATION.md` already
  exists in this repo — it's the Phase 8 Verdict Accuracy Tracker
  methodology doc (T-087–T-093), a different and already-shipped kind of
  evaluation (post-hoc market-outcome scoring, not pre-release LangSmith
  test suites). Overwriting it would destroy real, in-use documentation
  for a shipped feature. This task's actual deliverable is written to
  **`docs/EVAL_FRAMEWORK_DESIGN.md`** instead, and covers exactly what the
  acceptance criterion asks for (criteria + rubrics + grading scale per
  agent) under a name that doesn't collide with existing docs or with
  T-072 ("Write `EVALUATION.md`"), a separate later task in the same
  phase whose job is to write the canonical `EVALUATION.md`. See
  `docs/EVAL_FRAMEWORK_DESIGN.md` §6 for the full reasoning and the
  pointer left for T-072.

## Design decisions

- **Docs-only scope, deliberately.** The task type is `Planning`, 3
  estimated hours, and the description says "write rubrics" — not "build
  evals." Writing evaluator code now (ahead of T-068–T-071) would mean
  building against criteria that haven't been reviewed yet, and would
  blur the git history between "design" and "build" commits that the
  Excel plan intentionally separates into 4 different branches/PRs. No
  Python files change in this PR, so no lint/type/test surface is
  touched.
- **Filename collision resolved by not colliding, not by overwriting.**
  See the acceptance-criteria note above. The alternative (overwrite
  `docs/EVALUATION.md`) would silently delete the Phase 8 documentation
  that the README's live accuracy badge and the `/accuracy` dashboard
  page depend on being explained somewhere.
- **Grounded in the actual output schemas, not generic eval boilerplate.**
  Every rubric in `EVAL_FRAMEWORK_DESIGN.md` cites the exact
  `output_models.py` field it checks (e.g. `ContrarianReport
  .counter_arguments`, `InvestmentDecision.contrarian_response`,
  `FundamentalAnalysis.data_quality`) so T-068–T-071 can implement
  directly against field names that already exist, rather than inventing
  new ones.
- **Memo completeness is a shared helper, not a fifth build task.** The
  Excel plan only allocates T-068–T-071 to fundamental/sentiment/debate
  quality/latency — there's no dedicated "memo completeness" task.
  `EVAL_FRAMEWORK_DESIGN.md` §3.4 designs it as a reusable assertion
  helper any of the four build tasks' LangSmith experiments can import,
  rather than silently dropping the criterion or inventing an
  unplanned task.
- **LangSmith evals are scoped out of the standard CI gate**, same
  reasoning already established for T-106's manual QA script: they call
  a real LLM, cost real tokens, and need a live `LANGSMITH_API_KEY`.
  §4 of the design doc specifies each build task should ship a
  synthetic-mock unit test for the *evaluator function's own grading
  logic* (deterministic, CI-safe) separately from the real-LangSmith
  experiment script (manually run) — mirroring how `test_tracing.py`
  mocks `configure_tracing()` instead of hitting real LangSmith.
- **Open questions left open, not silently resolved.** §7 of the design
  doc flags three decisions (ground-truth dataset authoring effort, debate
  fixture reuse, and the novelty-check similarity threshold) that need
  empirical tuning once real agent output is available — deferring them
  to the relevant build task rather than guessing a number now that would
  need to be redone anyway.

## Files changed / created

| File | Type | Purpose |
| --- | --- | --- |
| `docs/EVAL_FRAMEWORK_DESIGN.md` | New | The eval framework design: criteria, datasets, rubrics, grading scale, and LangSmith wiring plan for T-068–T-071 |
| `docs/week-26/T-067-eval-framework-design.md` | New | This file — full workflow doc for T-067 |

No backend, frontend, migration, or test files are touched by this task.

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/eval-framework-design

git branch
# → * feat/eval-framework-design
```

### Step 2 — Add the design document

```bash
# docs/EVAL_FRAMEWORK_DESIGN.md
```

### Step 3 — Add this workflow doc

```bash
# docs/week-26/T-067-eval-framework-design.md
```

### Step 4 — Run the verification gate locally

This is a docs-only PR — no Python or TypeScript files change — but run the
full gate anyway so CI has zero surprises, per project convention. Windows
Git Bash: remember `ENVIRONMENT=test` cannot be chained with `&&` on this
machine; set it as its own line.

```bash
set ENVIRONMENT=test
python -m black backend --check
python -m isort backend --check
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v
```

Expect **no diffs and no failures** — none of these tools touch `docs/`, so
this step is purely a sanity check that the branch wasn't cut from a
half-broken `main`. If pre-commit hooks fail with `WinError 4551` (Windows
App Control blocking the shim), use the established workaround:

```bash
git commit --no-verify -m "..."
```

GitHub Actions' Linux runners remain the real enforcement gate. Both CI jobs
(`backend`, `frontend`) run unchanged and pass trivially — this task adds no
code for either to lint, type-check, or test.

### Step 5 — Commit

```bash
git add docs/EVAL_FRAMEWORK_DESIGN.md
git add docs/week-26/T-067-eval-framework-design.md

git commit --no-verify -m "docs(eval): design LangSmith evaluation framework

- Add docs/EVAL_FRAMEWORK_DESIGN.md: defines eval criteria, datasets,
  rubrics, and grading scale for all five task-spec criteria
  (fundamental accuracy, sentiment direction, contrarian novelty,
  memo completeness, latency <90s), each grounded in the exact
  output_models.py fields it checks
- Fundamental accuracy (T-068): 5-company dataset spanning
  strong/neutral/weak/insufficient-data buckets; directional
  agreement + honest-abstention rubric; >70% accuracy target
- Sentiment direction (T-069): 10 news-set + 3 known-scandal
  dataset; directional accuracy + red-flag detection rubrics;
  >80% / 3-of-3 targets
- Debate quality (T-070): reuses live InvestmentState snapshots;
  all-or-nothing rubric for Contrarian disagreement, non-repetition,
  and Portfolio Manager engagement with the debate
- Memo completeness: shared assertion helper against
  InvestmentDecision, reusable across T-068-T-071 rather than a
  standalone sixth task
- Latency (T-071): p50 <90s / p95 <120s targets, per-node breakdown
  sourced from tracing.py's existing @traced_agent instrumentation
- Documents LangSmith dataset/experiment naming conventions and
  scopes real-LangSmith eval runs out of the standard CI gate
  (mirrors T-106's manual-QA-script precedent)
- Deliberately does NOT overwrite the existing docs/EVALUATION.md
  (Phase 8 Verdict Accuracy Tracker doc, T-087-T-093) -- names this
  deliverable docs/EVAL_FRAMEWORK_DESIGN.md instead and leaves an
  explicit pointer for T-072 to reconcile the two documents

Closes #67"
```

If a formatter modifies files after staging (not expected here, since no
Python/TypeScript files are touched), re-stage and make a second, separate
commit rather than amending:

```bash
git add -A
git commit --no-verify -m "style: apply formatting to T-067 files"
```

### Step 6 — Push and open the PR

```bash
git push -u origin feat/eval-framework-design
```

**Base branch:** `main`
**Compare branch:** `feat/eval-framework-design`

## Pull Request

**Title:** `feat(eval): design and document evaluation criteria and rubrics for all agents`

### Summary

Designs AIRP's LangSmith evaluation framework ahead of T-068–T-071: defines
the dataset, rubric, and grading scale for each of the five eval criteria
named in the task spec (fundamental accuracy, sentiment direction,
contrarian novelty, memo completeness, latency <90s), grounded directly in
the existing `output_models.py` schemas and `tracing.py` instrumentation.
Docs-only — no agent, evaluator, or test code in this PR; that's T-068–T-071.

### Changes

- New `docs/EVAL_FRAMEWORK_DESIGN.md`: full design doc — criteria,
  per-agent dataset shape, rubric, grading scale, and a LangSmith
  dataset/experiment/evaluator naming convention shared across T-068–T-071
- New `docs/week-26/T-067-eval-framework-design.md`: this task's workflow
  doc
- **No code changes.** No backend, frontend, migration, or test files
  touched.

### Testing

- `python -m black backend --check` / `isort --check` / `flake8` / `mypy`
  — all clean (no Python files changed)
- `python -m pytest backend/tests/unit -v` — full existing suite still
  green (unaffected by this PR)
- Manual review: every rubric in the design doc cross-checked against the
  live field names in `backend/agents/output_models.py` to confirm nothing
  references a field that doesn't exist

### LangSmith Trace

Not applicable — this PR adds no code that calls an agent or LLM. The
design doc's §4 specifies the LangSmith dataset/experiment naming
convention that T-068–T-071 will use when they start producing real traces.

### Screenshots

Not applicable — docs-only change.

### Related Issues

Closes #67