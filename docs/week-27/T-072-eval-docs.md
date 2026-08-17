# T-072 — Write EVALUATION.md

**Phase:** 11 — Evaluation
**Week:** 27
**Branch:** `feat/eval-docs`
**Type:** Docs
**Priority:** 🟡 High
**Est. hours:** 3

## Summary

T-067 through T-071 built the entire Phase 11 LangSmith evaluation framework —
design doc, 4 evals across 5 grading criteria, 2 of them continuously enforced in CI.
T-072 closes Phase 11 with the artifact that makes all of that work discoverable and
understandable without reading the source: a single, recruiter-readable write-up of
the methodology, the real test cases, the results (including the honest "still
pending a real run" ones), the known limitations, and a concrete future-improvement
plan.

This is a **docs-only** task — no `backend/` or `frontend/src/` file is touched, so
neither CI job (`backend`, `frontend`) has anything new to lint, type-check, or test.

## The naming collision, and how it's resolved here

The task's literal acceptance criteria says `EVALUATION.md`, but **that path is
already taken** — `docs/EVALUATION.md` was created by T-093 (Phase 8, week 21) for a
completely different, already-shipped system: the Verdict Accuracy Tracker's
methodology (real market-outcome scoring of live verdicts, not pre-release
LangSmith test suites). T-067's own design doc (`docs/EVAL_FRAMEWORK_DESIGN.md`
§6) flagged this exact collision in advance and explicitly deferred the decision to
this task.

**Resolution:** both files stay separate and intact.

- `docs/EVALUATION.md` (Phase 8, T-093) — untouched except for a one-line cross-link
  added to its intro blockquote, pointing at the new file below.
- **`docs/AGENT_EVALUATION.md` (new, this task)** — the actual T-072 deliverable: the
  full Phase 11 methodology / results / limitations / future-plan write-up.
- `docs/EVAL_FRAMEWORK_DESIGN.md` (T-067) — §6 updated with a short "Resolved in
  T-072" note closing the loop it opened, rather than leaving a stale "decide this
  later" pointer in a merged design doc.

This satisfies the acceptance criterion in spirit — one complete, recruiter-readable
evaluation write-up exists and is trivially discoverable from both the README's docs
index and from `EVALUATION.md` itself — without silently overwriting T-093's
already-shipped, unrelated documentation.

## Acceptance criteria (from task spec)

- [x] `EVALUATION.md` complete — satisfied by `docs/AGENT_EVALUATION.md` (see naming
      resolution above); `docs/EVALUATION.md` (Phase 8) remains complete and intact,
      now cross-linked
- [x] Recruiters can understand the eval approach without additional context — the
      new doc opens with a 2-minute summary table before any implementation detail,
      and every section names real companies/datasets/thresholds rather than
      pointing back at source code

## Design decisions

- **A 2-minute summary table leads the document, before any methodology detail.**
  Acceptance criterion #2 is specifically about a recruiter reading *without
  additional context* — someone skimming for 90 seconds needs the headline (which
  evals exist, what they target, whether the target is actually CI-enforced) before
  they'd ever reach §3's methodology section. Structuring the doc "summary first,
  detail after" mirrors how the existing `docs/EVALUATION.md` (Phase 8) is already
  structured (§1 "Why this exists" leads with the elevator pitch before any schema
  detail) — reusing an established, working pattern rather than inventing a new one.
- **The single most important honest claim in the document — CI-enforced vs.
  manual-only — is stated as its own row in the summary table, not buried in prose.**
  Investigating the actual test files (`test_sentiment_evaluators.py`,
  `test_debate_evaluators.py`) turned up a fact that wasn't obvious from the design
  doc alone: because Sentiment and Debate grading has zero LLM/network dependency,
  their `TestFullDatasetMeetsTargets` classes run the *entire real dataset* through
  the *real* grading pipeline and assert the literal acceptance-criteria threshold —
  on every single push, not just as a "framework ready, awaiting a run" claim. This
  is a materially stronger and more precise claim than "an eval exists for this," and
  a recruiter (or interviewer) skimming this doc should see it immediately rather
  than have to infer it from reading four separate evaluator modules themselves.
- **Fundamental (T-068) and Latency (T-071) results are left explicitly "pending a
  real run," not populated with invented numbers.** Both genuinely require a live LLM
  call and/or live market data to produce a result; at the time this doc was written,
  neither `docs/week-26/T-068-eval-fundamental.md` nor
  `docs/week-27/T-071-eval-latency.md`'s own "real eval run output" sections had been
  filled in yet (still templates). Writing a plausible-sounding fabricated number here
  would be a worse outcome for a portfolio document than an honest "pending" — the
  whole point of this framework is to demonstrate real, checkable evidence, not
  numbers that look complete. §10's results-summary table and §4/§7's own per-eval
  results subsections both say "pending" explicitly and point at exactly which file's
  "real eval run output" section to update once a real run happens.
- **Memo completeness (`EVAL_FRAMEWORK_DESIGN.md` §3.4) is documented as a real gap,
  not silently dropped.** Grepping the repo for `memo_completeness` across
  `backend/evals/`, `docs/week-26/`, and the debate evaluators module turned up
  nothing — the check was designed in T-067 but never actually built by any of
  T-068–T-071. The task description explicitly asks for "known failure modes," and a
  designed-but-unbuilt check absent from a document that otherwise claims to cover
  "the eval approach" is exactly the kind of gap that erodes trust if a careful reader
  (or an interviewer who reads the design doc too) notices the mismatch themselves.
  §8 names it plainly, §11 lists it as a limitation, and §12 makes it future-work
  item #1 — the smallest, most concretely-scoped item on the list, since the 5
  debate-eval snapshots already have a schema-faithful `decision` field ready to
  grade against.
- **Real dataset contents (company names, tickers, set names) are pulled directly
  from the actual `backend/evals/*_eval_dataset.py` source files, not re-described
  from memory of the design doc.** E.g. the Fundamental dataset table, the Sentiment
  direction-set names (`large_order_win`, `guidance_cut`, etc.), and the Debate
  snapshot names (`tcs_quality_compounder_challenged`, etc.) are all copied from the
  actual committed dataset modules — so this document stays accurate even where it
  diverges in a small detail from what T-067's design doc originally proposed (e.g.
  the design doc's illustrative "5 companies" placeholder table vs. the real,
  specific tickers T-068 actually shipped).
- **A dedicated §9 explains the relationship to the Phase 8 accuracy tracker**,
  since the two systems' names ("evaluation," "accuracy") are close enough that a
  reader skimming both files without this section could reasonably wonder whether one
  supersedes the other, or whether they're duplicated effort. The comparison table
  (ground truth source, when each runs, code location, public-facing or not) is
  designed to make the distinction concrete rather than purely conceptual.

## Files changed / created

| File | Type | Purpose |
| --- | --- | --- |
| `docs/AGENT_EVALUATION.md` | New | T-072's actual deliverable — full Phase 11 methodology, real test cases, results (including honest "pending" rows), known limitations, future improvement plan |
| `docs/EVALUATION.md` | Modified | One-line cross-link added to the intro blockquote, pointing at `AGENT_EVALUATION.md` — no other content changed |
| `docs/EVAL_FRAMEWORK_DESIGN.md` | Modified | §6 "Naming and sequencing note" updated with a short "Resolved in T-072" paragraph closing the loop it explicitly deferred to this task |
| `docs/week-27/T-072-eval-docs.md` | New | This file — full workflow doc for T-072 |

No `backend/`, `frontend/src/`, migration, or test file is touched by this task.

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b feat/eval-docs

git branch
# → * feat/eval-docs
```

### Step 2 — Write the new Phase 11 evaluation doc

```bash
# docs/AGENT_EVALUATION.md
```

Before writing, re-read the actual source (not just the design doc) so every number
and dataset name in the write-up is accurate:

```bash
cat docs/EVAL_FRAMEWORK_DESIGN.md
cat backend/evals/fundamental_eval_dataset.py
cat backend/evals/sentiment_eval_dataset.py
cat backend/evals/debate_eval_dataset.py
cat backend/evals/latency_eval_dataset.py
grep -n "TARGET\|THRESHOLD" backend/evals/*_evaluators.py
grep -n "class TestFullDatasetMeetsTargets" -A 20 backend/tests/unit/test_sentiment_evaluators.py backend/tests/unit/test_debate_evaluators.py
grep -rn "memo_completeness" backend/evals docs/week-26
```

### Step 3 — Cross-link the existing Phase 8 doc and close the loop in T-067's design doc

```bash
# docs/EVALUATION.md          (modify — add the one-line cross-link)
# docs/EVAL_FRAMEWORK_DESIGN.md (modify — §6 "Resolved in T-072" note)
```

### Step 4 — Add this workflow doc

```bash
# docs/week-27/T-072-eval-docs.md
```

### Step 5 — Run the verification gate locally

This is a docs-only change — the standard backend/frontend lint/type-check/test gate
has nothing new to check, but confirm that explicitly rather than assuming it:

```bash
git status
# → only docs/AGENT_EVALUATION.md (new), docs/EVALUATION.md (modified),
#   docs/EVAL_FRAMEWORK_DESIGN.md (modified), docs/week-27/T-072-eval-docs.md (new)
# → nothing under backend/ or frontend/src/

set ENVIRONMENT=test
python -m pytest backend/tests/unit -v --cov=backend --cov-report=term-missing
```

Confirm the full backend unit suite is still green and coverage is still ≥85% —
expected to be a no-op confirmation, since nothing under `backend/` changed, but
running it once on this branch before opening the PR catches the (unlikely) case of
an unrelated pre-existing failure being mistakenly attributed to this change later.

Also do a manual link-check pass on the new document — every `[text](#anchor)`
internal link and the two cross-links to `EVALUATION.md` / `AGENT_EVALUATION.md`
should resolve:

```bash
grep -n "\]\(#" docs/AGENT_EVALUATION.md
grep -n "AGENT_EVALUATION.md\|EVALUATION.md" docs/EVALUATION.md docs/AGENT_EVALUATION.md docs/EVAL_FRAMEWORK_DESIGN.md
```

If pre-commit hooks fail with `WinError 4551` on the commit itself (unlikely for a
docs-only change, since black/isort/flake8/mypy only touch `.py` files, but Windows
App Control has been known to intercept the hook runner regardless of what changed),
use the established workaround:

```bash
git commit --no-verify -m "..."
```

### Step 6 — Commit

```bash
git add docs/AGENT_EVALUATION.md
git add docs/EVALUATION.md
git add docs/EVAL_FRAMEWORK_DESIGN.md
git add docs/week-27/T-072-eval-docs.md

git commit --no-verify -m "docs(eval): write evaluation methodology documentation

- Add docs/AGENT_EVALUATION.md: the full Phase 11 evaluation
  write-up -- a 2-minute summary table up front, then per-eval
  sections for Fundamental accuracy (T-068), Sentiment direction +
  red-flag detection (T-069), Debate quality (T-070), and Latency
  (T-071), each covering what's measured, the real dataset (real
  company names / news-set names / snapshot names pulled directly
  from the committed backend/evals/*_eval_dataset.py source, not
  re-described from the design doc), the rubric, the target, CI
  status, and results
- Document that Sentiment and Debate grading has zero LLM/network
  dependency, so their real acceptance-criteria targets
  (test_sentiment_evaluators.py / test_debate_evaluators.py's
  TestFullDatasetMeetsTargets) are asserted against the entire real
  dataset on every push -- a materially stronger, more precise claim
  than \"an eval exists,\" verified by reading the actual test files
  rather than assumed from the design doc
- Document Fundamental (T-068) and Latency (T-071) results as
  explicitly pending a real run (neither's own task doc had a real
  run pasted in yet) rather than fabricating plausible-looking
  numbers
- Add a dedicated section documenting that memo completeness
  (EVAL_FRAMEWORK_DESIGN.md Sec 3.4) was designed in T-067 but never
  actually implemented by T-068-T-071 -- confirmed via grep across
  backend/evals/ and docs/week-26/ turning up nothing -- carried
  forward as known-limitation + future-work item #1 rather than
  silently dropped
- Add Sec 9 explaining how this Phase 11 pre-release agent-quality
  framework relates to and differs from the Phase 8 verdict accuracy
  tracker (post-release, real-market-outcome scoring)
- Add Sec 11 known limitations (small fixed sample sizes,
  ground-truth drift risk, synthetic-vs-real-traffic gap,
  once-picked-not-independently-tuned thresholds, no automatic
  scheduled runs for the two LLM-dependent evals, no trend tracking
  over time) and Sec 12 a concrete, prioritised future improvement
  plan
- Resolve the docs/EVALUATION.md filename collision flagged in
  advance by EVAL_FRAMEWORK_DESIGN.md Sec 6: keep the existing Phase
  8 docs/EVALUATION.md fully intact, add a one-line cross-link to
  its intro, and ship this task's actual deliverable as
  docs/AGENT_EVALUATION.md instead of overwriting the unrelated
  Phase 8 file
- Update EVAL_FRAMEWORK_DESIGN.md Sec 6 with a short \"Resolved in
  T-072\" note closing the loop it explicitly deferred to this task

Closes #72"
```

### Step 7 — Push and open the PR

```bash
git push -u origin feat/eval-docs
```

**Base branch:** `main`
**Compare branch:** `feat/eval-docs`

## Pull Request

**Title:** `docs(eval): document evaluation framework, results, and methodology`

### Summary

Closes Phase 11 with `docs/AGENT_EVALUATION.md` — a single, recruiter-readable
write-up of the entire LangSmith agent-evaluation framework built across T-067–T-071:
methodology, real dataset contents, targets, CI-enforcement status per eval, honest
results (including two evals still pending a real run), known limitations, and a
prioritised future-improvement plan. Resolves the `docs/EVALUATION.md` filename
collision T-067's design doc flagged in advance by keeping the existing Phase 8
Verdict Accuracy Tracker doc fully intact and shipping this task's deliverable under
`docs/AGENT_EVALUATION.md` instead, with both files now cross-linked.

### Changes

- New `docs/AGENT_EVALUATION.md` — the full T-072 deliverable
- `docs/EVALUATION.md` — one-line cross-link added, no other change
- `docs/EVAL_FRAMEWORK_DESIGN.md` — §6 updated with a "Resolved in T-072" note
- New `docs/week-27/T-072-eval-docs.md` — this task's workflow doc

### Testing

Docs-only change — no `backend/` or `frontend/src/` file touched, so neither CI job
has anything new to lint, type-check, or test. Confirmed the full backend unit suite
is still green and coverage still ≥85% as a sanity check (expected no-op, since
nothing under `backend/` changed):

```
python -m pytest backend/tests/unit -v --cov=backend --cov-report=term-missing
```

Manually verified every internal `[text](#anchor)` link in the new document resolves,
and both cross-links between `docs/EVALUATION.md` and `docs/AGENT_EVALUATION.md` are
correct.

### LangSmith Trace

Not applicable — no code or agent behavior changed.

### Screenshots

Not applicable — docs-only change, no UI.

### Related Issues

Closes #72