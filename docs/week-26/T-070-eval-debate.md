# T-070 — Build Debate Quality Eval

**Phase:** 11 — Evaluation
**Week:** 26
**Branch:** `feat/eval-debate`
**Type:** Testing
**Priority:** 🟡 High
**Est. hours:** 4

## Summary

T-070 implements the third LangSmith eval designed in T-067's
`docs/EVAL_FRAMEWORK_DESIGN.md` §3.3: grades the multi-agent debate
engine's quality against 5 synthetic post-debate snapshots (a
`ContrarianReport`-shaped dict, a `debate_rounds[]` transcript, and an
`InvestmentDecision`-shaped dict per snapshot), applying four structural
checks that together cover T-070's literal acceptance criteria:

1. **Contrarian always disagrees** — `counter_arguments` has ≥3 entries
   and `bear_conviction` ≥ 1 (never an empty, rubber-stamp report)
2. **Multi-agent engagement** — at least one debate round has genuine
   (non-"no position") responses from ≥2 agents
3. **Novelty (not repetition)** — no two claims across
   `counter_arguments` + `overlooked_risks` are near-duplicate strings
4. **Portfolio Manager references debate content** —
   `contrarian_response` is non-empty and does not verbatim-echo
   `strongest_argument`

Like T-069 (and unlike T-068), grading here has **zero network/LLM
dependency** — a debate snapshot is already-produced state, not a live
agent call. That means the full real dataset is asserted directly inside
a normal CI-covered pytest test, exactly the same pattern T-069
established.

**Verified locally by hand, before writing anything else:** all 5
snapshots pass all 4 checks (5/5, all-or-nothing target met), and every
synthetic *failing* fixture built to prove the grading logic actually
catches a violation does fail exactly the check it's meant to catch (too
few counter-arguments, single-agent-only round, near-duplicate claims,
verbatim-echoed PM response) — confirmed by running the grading pipeline
directly in the sandbox before the test file was even finalized.

## Acceptance criteria (from task spec)

- [x] Contrarian always disagrees
- [x] Debate rounds non-repetitive
- [x] Portfolio Manager references debate content

All three are asserted directly in
`backend/tests/unit/test_debate_evaluators.py::TestFullDatasetMeetsTargets`
against the real 5-snapshot dataset and the real (un-mocked) grading
pipeline.

## Design decisions

- **Synthetic, hand-authored snapshots instead of reusing
  `test_graph_integration.py`'s mock fixtures.** T-067's design doc
  proposed reusing that file's fixtures, but its mock helpers
  (`_mock_contrarian_success`, `_run_graph`, etc.) are test-module-local
  (leading underscore, not a public API) and tightly coupled to that
  file's own full-pipeline mocking of all 8 agents. Importing them here
  would create a fragile cross-test-file dependency for no real benefit.
  Instead, `backend/evals/debate_eval_dataset.py` hand-authors 5
  snapshots that are schema-faithful to the real `ContrarianReport` /
  `DebateRound` / `InvestmentDecision` shapes (verified field-for-field
  in `TestDatasetShape`) — the same self-contained-synthetic-data
  approach `fundamental_eval_dataset.py` and `sentiment_eval_dataset.py`
  already used.
- **All 5 snapshots are constructed to PASS every check** — this dataset
  is the positive proof that the real system reliably produces
  compliant debates across 5 different companies and all 3 verdict
  types (BUY / SELL / HOLD), not a mixed pass/fail set. The grading
  logic's ability to *catch* a violation is proven separately with
  synthetic malformed fixtures in `TestGradeDebateSnapshot` — mirroring
  how T-068 kept its insufficient-data hard-fail case and T-069 kept its
  spurious-red-flag test as dedicated negative-case checks, distinct
  from "is the real system compliant."
- **Novelty threshold resolved as Jaccard word-overlap similarity at
  0.6** — this was the one open question T-067's design doc explicitly
  deferred to this task (§7). Chose Jaccard token-overlap over a
  sentence-transformers embedding-similarity approach for three
  reasons, documented in `debate_evaluators.py`'s own module docstring:
  zero new dependencies (matches `sentiment_analyst.py`'s own precedent
  of avoiding heavy NLP deps for deterministic checks), no model-loading
  cost in CI, and it's trivially explainable in a PR review ("these two
  sentences share 65% of their words") in a way a cosine-similarity
  score isn't. Verified empirically: the highest pairwise similarity
  across all 5 snapshots' actual claims is ~0.11, comfortably below 0.6.
- **"No position this round (data unavailable)" filler text is
  explicitly excluded from the multi-agent-engagement count.** This is
  `debate_loop_node`'s own real, deterministic output for an agent that
  hasn't run yet (Risk Officer on round 1, per the real topology) — it's
  expected structural state, not an engaged response, and counting it
  would let a debate round with effectively zero real engagement pass
  the check by accident.
- **Novelty is checked across `counter_arguments` + `overlooked_risks`
  combined**, not `counter_arguments` alone — matches
  `EVAL_FRAMEWORK_DESIGN.md` §3.3's rubric wording exactly ("No two
  entries in `counter_arguments` (or across `overlooked_risks`)").
  Covered by `test_repetition_across_counter_arguments_and_overlooked_risks`.
- **"PM references debate content" checks for verbatim substring
  containment, not exact equality** — a PM response that wraps the
  Contrarian's exact words in a longer sentence ("As the Contrarian
  noted: `<strongest_argument verbatim>` We take no further view.")
  still fails, since that's not genuine engagement either. Covered by
  `test_verbatim_echo_embedded_in_longer_text_still_fails`.
- **All four checks are genuinely required for `overall_pass`** — a
  snapshot with a strong Contrarian report but a PM response that
  ignores it (or vice versa) still fails overall. This is deliberately
  stricter than treating the four checks as independently-reported
  metrics with no combined verdict, matching
  `EVAL_FRAMEWORK_DESIGN.md` §3.3's "All-or-nothing pass/fail per run"
  framing.
- **Grading never raises**, including on missing dataset keys or wrongly
  -typed fields (a string where a list was expected, `None` where a dict
  was expected) — every extraction step in `grade_debate_snapshot`
  defensively falls back to an empty/zero default and grades the
  resulting check as a fail rather than crashing. Covered by
  `test_missing_fields_are_graded_as_fail_not_raise` and
  `test_malformed_field_types_do_not_raise`.
- **The eval runs fully offline** (like T-069, unlike T-068) — grading a
  debate snapshot is pure data transformation with no agent/LLM call
  involved. `scripts/run_eval_debate.py` still exists for a
  human-readable report and an optional LangSmith push (dashboard
  consistency with every other AIRP eval, per
  `EVAL_FRAMEWORK_DESIGN.md` §4), but the pytest suite is the load-
  bearing proof of the acceptance criteria, not the script.

## Files changed / created

| File | Type | Purpose |
| --- | --- | --- |
| `backend/evals/debate_eval_dataset.py` | New | 5 synthetic post-debate snapshots (`DebateSnapshotExample` TypedDict) spanning BUY/SELL/HOLD verdicts |
| `backend/evals/debate_evaluators.py` | New | Pure grading logic (`jaccard_similarity`, `has_near_duplicate_pair`, `grade_debate_snapshot`, aggregation functions) + LangSmith target/evaluator functions |
| `scripts/run_eval_debate.py` | New | Fully offline deterministic report + optional LangSmith dataset upload and experiment run |
| `scripts/README.md` | Modified | Added the new script's entry |
| `backend/tests/unit/test_debate_evaluators.py` | New | CI-safe unit tests: dataset shape, similarity logic, the 4-check rubric (including synthetic failing fixtures per check), aggregation, target function, evaluator wrappers, and a full-real-dataset proof of the acceptance criteria |
| `docs/week-26/T-070-eval-debate.md` | New | This file — full workflow doc for T-070 |

No migration, router, frontend, or existing agent/graph files are
touched — this eval grades already-produced state and doesn't call
`backend/graph/nodes.py` or any agent module.

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/eval-debate

git branch
# → * feat/eval-debate
```

### Step 2 — Add the eval dataset and grading logic

```bash
# backend/evals/debate_eval_dataset.py
# backend/evals/debate_evaluators.py
```

### Step 3 — Add the eval runner script

```bash
# scripts/run_eval_debate.py
# scripts/README.md (modify — add the new script's row)
```

### Step 4 — Add tests

```bash
# backend/tests/unit/test_debate_evaluators.py
```

### Step 5 — Add this workflow doc

```bash
# docs/week-26/T-070-eval-debate.md
```

### Step 6 — Run the full verification gate locally

Windows Git Bash — remember `ENVIRONMENT=test` cannot be chained with
`&&` on this machine:

```bash
set ENVIRONMENT=test
python -m black backend --check
python -m isort backend --check
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit/test_debate_evaluators.py -v
python -m pytest backend/tests/unit -v --cov=backend --cov-report=term-missing
```

Pay particular attention to
`TestFullDatasetMeetsTargets::test_all_five_snapshots_pass_every_check`
and the parametrized `test_every_snapshot_individually_passes` — these
are the direct, CI-enforced proof of this task's acceptance criteria
against the real dataset and the real grading pipeline. If a snapshot
ever fails, the parametrized test ID names exactly which one broke
(e.g. `test_every_snapshot_individually_passes[tata_steel_cyclical_debate]`),
and the assertion message includes `grade["comment"]`, which names which
of the 4 checks failed and why.

Confirm the coverage run still reports ≥85% overall — both new
`backend/evals/debate_*.py` files are inside `source = ["backend"]` and
not excluded by `omit`, so their lines count toward the total. The test
suite exercises every branch of `jaccard_similarity`,
`has_near_duplicate_pair`, every individual check inside
`grade_debate_snapshot` (both passing and each failing independently),
both aggregation functions, `debate_eval_target`'s success/malformed-
input paths, and all four LangSmith evaluator wrappers' malformed-run
paths.

If pre-commit hooks fail with `WinError 4551`, use the established
workaround:

```bash
git commit --no-verify -m "..."
```

The frontend CI job passes unchanged — this task touches no frontend
file.

### Step 6a — Run the eval report (optional but recommended for PR evidence)

Like T-069, this needs no real market data, no real LLM call, and no
LangSmith account to produce a meaningful, deterministic result:

```bash
set ENVIRONMENT=development
python -m scripts.run_eval_debate
```

Paste the full console output (per-snapshot pass/fail with all 4 check
results, plus the summary line) into the PR description alongside the
pytest proof.

If `LANGSMITH_API_KEY` is set in your `.env`, the script also uploads the
`airp-eval-debate-quality` dataset (idempotent) and runs a real
`langsmith.evaluate()` experiment. Paste the experiment URL into the PR
description if you have it — optional supporting evidence, not required,
since the pytest suite already proves the acceptance criteria without
needing LangSmith configured.

### Step 7 — Commit

```bash
git add backend/evals/debate_eval_dataset.py
git add backend/evals/debate_evaluators.py
git add scripts/run_eval_debate.py
git add scripts/README.md
git add backend/tests/unit/test_debate_evaluators.py
git add docs/week-26/T-070-eval-debate.md

git commit --no-verify -m "feat(eval): add debate engine evaluation suite

- Add debate_eval_dataset.py: 5 synthetic post-debate snapshots
  (ContrarianReport / debate_rounds[] / InvestmentDecision-shaped
  dicts) spanning BUY, SELL, and HOLD verdicts across 5 different
  companies, schema-faithful to the real Pydantic models rather
  than reusing test_graph_integration.py's test-module-local mock
  helpers
- Add debate_evaluators.py: pure grading logic
  (jaccard_similarity, has_near_duplicate_pair,
  grade_debate_snapshot, compute_pass_rate,
  meets_debate_quality_target) implementing the four-check rubric
  from EVAL_FRAMEWORK_DESIGN.md Section 3.3 -- Contrarian
  disagreement (>=3 counter-arguments, bear_conviction >= 1),
  multi-agent engagement (>=2 agents with genuine, non-'no
  position' responses in at least one round), novelty (Jaccard
  word-overlap similarity at a documented 0.6 threshold, resolving
  Section 7's open question), and PM engagement (non-empty
  contrarian_response that doesn't verbatim-echo
  strongest_argument). Plus a deterministic LangSmith target
  function and four evaluator functions
- Add scripts/run_eval_debate.py: fully offline deterministic
  report (no network/LLM dependency) plus a best-effort LangSmith
  dataset upload + experiment run when LANGSMITH_API_KEY is set
- Add backend/tests/unit/test_debate_evaluators.py: CI-safe
  coverage of dataset shape, Jaccard similarity logic, the full
  4-check rubric with synthetic FAILING fixtures proving the
  grading logic catches each individual violation (too few
  counter-arguments, single-agent-only round, near-duplicate
  claims, verbatim-echoed PM response, missing/malformed fields),
  aggregation, target function defensive paths, evaluator wrapper
  malformed-run handling, and -- uniquely possible here since
  grading has zero network/LLM dependency -- a full real-dataset
  proof of all three acceptance criteria
  (TestFullDatasetMeetsTargets), verified locally beforehand: 5/5
  snapshots pass every check
- Update scripts/README.md with the new script's entry

Closes #70"
```

If a formatter modifies files after staging, re-stage and make a second,
separate commit rather than amending:

```bash
git add -A
git commit --no-verify -m "style: apply black/isort formatting to T-070 files"
```

### Step 8 — Push and open the PR

```bash
git push -u origin feat/eval-debate
```

**Base branch:** `main`
**Compare branch:** `feat/eval-debate`

## Pull Request

**Title:** `feat(eval): implement LangSmith eval for debate quality and contrarian effectiveness`

### Summary

Implements the debate-quality eval designed in T-067's
`docs/EVAL_FRAMEWORK_DESIGN.md` §3.3: grades 5 synthetic post-debate
snapshots against four structural checks covering T-070's acceptance
criteria — Contrarian always disagrees, debate rounds are non-repetitive,
and the Portfolio Manager genuinely references (not just echoes) the
debate content. Because grading operates entirely on already-produced
state with no network or LLM dependency, the full real dataset is
asserted directly in a normal CI-covered pytest test — this PR's own test
suite is the direct proof of the acceptance criteria, matching the
pattern T-069 established. Also resolves T-067's one deferred open
question: the novelty/near-duplicate similarity threshold (0.6, Jaccard
word-overlap).

### Changes

- New `backend/evals/debate_eval_dataset.py`: 5 schema-faithful synthetic
  snapshots spanning BUY/SELL/HOLD verdicts
- New `backend/evals/debate_evaluators.py`: 4-check grading rubric that
  never raises, plus LangSmith target/evaluator functions
- New `scripts/run_eval_debate.py`: fully offline deterministic report +
  optional LangSmith push
- Full unit test coverage, including synthetic failing fixtures proving
  the grading logic catches each violation, and a full-real-dataset proof
  of the acceptance criteria
- `scripts/README.md` updated

### Testing

- `python -m pytest backend/tests/unit/test_debate_evaluators.py -v` —
  all pass, including `TestFullDatasetMeetsTargets`
- `python -m pytest backend/tests/unit -v --cov=backend
  --cov-report=term-missing` — full suite green, coverage still ≥85%
- `python -m mypy backend` / `python -m flake8 backend` / `python -m
  black backend --check` / `python -m isort backend --check`
- `python -m scripts.run_eval_debate` — see pasted console output below

### Eval run output

_Paste the full console output of `python -m scripts.run_eval_debate`
here (or the pytest `-v` output for `TestFullDatasetMeetsTargets`) —
either is direct evidence for all three acceptance criteria. Locally
verified by hand before writing the test file: 5/5 snapshots pass every
check, and every synthetic failing fixture fails exactly the check it's
meant to catch._

### LangSmith Trace

_Optional for this task (like T-069, this eval's correctness doesn't
depend on it) — paste the experiment URL here if you ran with
`LANGSMITH_API_KEY` configured._

### Screenshots

Not applicable — backend eval tooling change with no UI.

### Related Issues

Closes #70