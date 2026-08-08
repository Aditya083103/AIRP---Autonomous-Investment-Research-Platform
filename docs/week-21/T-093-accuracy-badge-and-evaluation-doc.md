# T-093 — Accuracy badge + EVALUATION.md update

**Phase:** 8 — Verdict Accuracy Tracker
**Week:** 21
**Branch:** `docs/accuracy-tracker-docs`
**Type:** Docs
**Priority:** 🟢 Medium
**Est. hours:** 2

## Summary

T-087 through T-092 built the entire Verdict Accuracy Tracker — schema, recording,
scheduled evaluation, the public API, and the public dashboard. T-093 closes Phase 8
with the two artifacts that make all of that work discoverable and understandable
without reading the source: a **live accuracy badge** on the README, and
**`docs/EVALUATION.md`**, a full write-up of the evaluation methodology (the
evaluation-horizon mapping and the dead-zone directional scoring rule) with worked
numeric examples.

This is a **docs-only** task — no `backend/` or `frontend/src/` files are touched, so
neither CI job (`backend`, `frontend`) has anything new to lint, type-check, or test.

## Acceptance criteria (from task spec)

- [x] README shows accuracy badge
- [x] `EVALUATION.md` explains horizon mapping and scoring rule with worked examples

## Design decisions

- **The badge is a `shields.io` "dynamic JSON" badge reading
  `overall_accuracy_pct` directly from the live `GET /api/v1/accuracy/summary`
  endpoint (T-091)** — not a separately generated/committed badge image, and not a new
  backend endpoint. `shields.io`'s `/badge/dynamic/json` endpoint can pull any field out
  of any public JSON URL via a JSONPath query (`$.overall_accuracy_pct`) with no
  backend changes at all — the endpoint T-091 already shipped is public and already
  returns exactly the field needed. This keeps the badge genuinely "live": it always
  reflects whatever the deployed API currently reports, with zero risk of it silently
  going stale the way a manually-updated static badge would.
- **The badge's target URLs are the placeholder production domains already present
  in `.env.example`** (`airp-api.onrender.com` for the API, `airp.vercel.app` for the
  frontend link) — Phase 12 (Deploy & Launch) has not run yet, so nothing is deployed
  there today. The badge will render `invalid` until Phase 12 ships, which is expected
  and called out explicitly in an HTML comment directly above it in the README, matching
  the file's own existing placeholder-comment convention (`<!-- Demo GIF will go here
  after Phase 8 -->`). No code changes are needed once deployment happens — the badge
  starts resolving live the moment the API is reachable at that URL.
- **`EVALUATION.md` is written entirely from the actual implementation**, not from the
  task-plan description — every constant (`DEAD_ZONE_PCT = 5.0`,
  `DEFAULT_EVALUATION_HORIZON_DAYS = 90`,
  `HIGH_CONFIDENCE_EVALUATION_HORIZON_DAYS = 365`), every boundary rule (the dead zone is
  an *open* interval; exactly ±5.0% counts as having left it), and every one of the four
  `time_horizon` label branches was read directly out of
  `backend/services/accuracy_tracker.py` and
  `backend/agents/portfolio_manager.py::_determine_time_horizon` before being
  transcribed into the doc, and every worked-example percentage was independently
  recomputed by hand to confirm it matches what the real scoring function would return.
- **Worked examples use three separate tables (BUY / SELL / HOLD)**, each anchored to a
  concrete `price_at_verdict`, rather than one abstract table of percentages — a reader
  should be able to see a real rupee price move to a real rupee price and know
  immediately whether AIRP would call that verdict right, including the exact boundary
  case (a move of precisely ±5.00%) for each verdict type.
- **The horizon-mapping worked example calls out the "12 months but scored at 90 days"
  case explicitly** — this is the single most surprising fact about the mapping (a
  memo's stated 12-month time horizon is not what the tracker actually waits for), and
  is exactly the kind of thing this document exists to make clear before someone has to
  go read the source to find it out.
- **README changes are narrowly scoped to only the badge and one new
  `Documentation` table row.** The README's `Status` table is visibly stale (every phase
  past 0 still reads "Not started" despite Phase 8 being nearly complete), but bringing
  it up to date is out of scope for this task and risks colliding with whatever later
  task is responsible for that update (likely part of Phase 12's launch polish) — T-093
  touches only what its own acceptance criteria calls for.
- **No backend or frontend files are touched.** Both CI jobs (`backend`: black/isort/
  flake8/mypy/pytest; `frontend`: tsc/eslint/prettier/vitest/build) are scoped to
  `backend/` and `frontend/` respectively (see `.github/workflows/ci.yml`); a change
  confined to the repo root and `docs/` cannot fail either job. The repo's own
  `.pre-commit-config.yaml` confirms the same scoping — even Prettier's Markdown
  formatting hook is scoped to `files: ^frontend/`, so root-level `README.md` and
  `docs/EVALUATION.md` are outside every automated formatting/lint gate in this repo.
  This document's Markdown is still hand-checked against the existing docs' own style
  (table alignment, TOC-with-anchors, `>` blockquote intro) for consistency, not because
  a linter would catch a mismatch.

## Files changed / created

### Root

- **`README.md`** (**MODIFY**) — adds the live accuracy badge (with its placeholder-URL
  explanatory comment) directly under the existing CI badge, and adds one new row to the
  `## Documentation` table linking `docs/EVALUATION.md`. Nothing else in the file
  changes.

### Docs

- **`docs/EVALUATION.md`** (**CREATE**) — the full evaluation methodology write-up:
  the record → wait → evaluate → aggregate → publish pipeline, the evaluation-horizon
  mapping table, the dead-zone scoring rule with its boundary semantics, three worked
  BUY/SELL/HOLD examples, the aggregation and public-API sections, a design-rationale
  FAQ, and a known-limitations section.
- **`docs/week-21/T-093-accuracy-badge-and-evaluation-doc.md`** (this file).

## Step-by-step: branch → commit → PR

### Step 1 — Sync `main` and cut the feature branch

```bash
git checkout main
git pull origin main

git checkout -b docs/accuracy-tracker-docs

git branch
# → * docs/accuracy-tracker-docs
```

### Step 2 — Re-read the actual implementation before writing anything

Before touching either doc, re-open the real source so every number and rule in
`EVALUATION.md` is transcribed, not guessed:

```bash
# The horizon mapping and dead-zone rule, with their full docstrings
sed -n '1,140p'   backend/services/accuracy_tracker.py
sed -n '180,220p' backend/services/accuracy_tracker.py   # derive_evaluation_horizon_days
sed -n '410,460p' backend/services/accuracy_tracker.py   # DEAD_ZONE_PCT, score_directional_correctness

# The four time_horizon labels the tracker's horizon mapping keys off of
grep -n "_determine_time_horizon" -A 20 backend/agents/portfolio_manager.py

# The "due" comparison run_due_evaluations actually uses
grep -n "_is_due" -A 15 backend/services/accuracy_tracker.py

# The public API shape EVALUATION.md's §6-7 describe
sed -n '1,60p' backend/routers/accuracy.py
```

### Step 3 — Write `docs/EVALUATION.md`

New file. See "Files changed / created" above for its full section list. Recompute
every worked-example percentage by hand against `score_directional_correctness`'s
actual rule before including it.

### Step 4 — Add the badge and doc link to `README.md`

- Add the `shields.io` dynamic-JSON accuracy badge directly under the existing CI
  badge, with the placeholder-URL explanatory HTML comment above it.
- Add one row to the `## Documentation` table linking `docs/EVALUATION.md`.

### Step 5 — Verify locally

This is a docs-only change with no automated gate covering it (see "Design decisions"
above), so verification is a manual read-through rather than a lint/test run:

```bash
# Confirm the badge Markdown renders (GitHub-flavoured Markdown preview in your
# editor, or push to a scratch branch and view the rendered README on GitHub)

# Confirm every internal doc link resolves
grep -n "docs/EVALUATION.md" README.md
ls docs/EVALUATION.md

# Confirm neither backend/ nor frontend/ was touched
git diff --stat main
```

`git diff --stat` should show only `README.md`,
`docs/EVALUATION.md`, and this workflow doc.

### Step 6 — Commit

```bash
git add README.md
git add docs/EVALUATION.md
git add docs/week-21/T-093-accuracy-badge-and-evaluation-doc.md

git commit -m "docs: document verdict accuracy tracker methodology

- Add a live shields.io accuracy badge to README.md, reading
  overall_accuracy_pct directly from the public
  GET /api/v1/accuracy/summary endpoint (T-091) -- no new backend code,
  no separate badge-generation step to keep in sync
- Add docs/EVALUATION.md: the full record -> wait -> evaluate ->
  aggregate -> publish pipeline, the evaluation-horizon mapping
  (90 vs. 365 days, and why only the high-margin-of-safety BUY case
  gets the long horizon), the +-5% dead-zone directional scoring rule
  with its open-interval boundary semantics, worked BUY/SELL/HOLD
  examples with real rupee prices, the aggregation/public-API sections,
  a design-rationale FAQ, and known limitations
- Add one Documentation table row in README.md linking the new doc
- No backend or frontend files touched -- both CI jobs are scoped to
  backend/ and frontend/ respectively and have nothing new to check

Closes #93"
```

No pre-commit formatting concerns here (Black/isort/flake8/mypy are all scoped to
`backend/`; Prettier's Markdown hook is scoped to `frontend/`) — a plain commit is
sufficient, no `--no-verify` workaround needed for this particular change.

### Step 7 — Push and open the PR

```bash
git push -u origin docs/accuracy-tracker-docs
```

**Base branch:** `main`
**Compare branch:** `docs/accuracy-tracker-docs`

## Pull Request

**PR title:**

```
docs: add accuracy badge and evaluation methodology writeup
```

**PR description:**

```markdown
## Summary
Closes out Phase 8 (Verdict Accuracy Tracker) with the two docs artifacts
the acceptance criteria call for: a live accuracy badge on the README,
and docs/EVALUATION.md -- a full methodology write-up of the
evaluation-horizon mapping and the dead-zone directional scoring rule,
with worked numeric examples.

## Changes
- README.md: adds a live shields.io dynamic-JSON badge reading
  overall_accuracy_pct from the public GET /api/v1/accuracy/summary
  endpoint (T-091) -- genuinely live, no separate badge-generation
  step. Points at the placeholder production URLs already in
  .env.example; will start resolving once Phase 12 deploys (explained
  in an HTML comment directly above the badge).
- README.md: one new Documentation table row linking docs/EVALUATION.md.
- docs/EVALUATION.md (new): the full record -> wait -> evaluate ->
  aggregate -> publish pipeline; the evaluation-horizon mapping table
  (90 vs. 365 days, with the "even a 12-month-labelled BUY is scored at
  90 days" nuance called out); the +-5% dead-zone scoring rule
  including its open-interval boundary semantics; three worked
  BUY/SELL/HOLD examples with real rupee prices and the exact ±5.00%
  boundary case for each; the aggregation and public-API sections; a
  design-rationale FAQ; and known limitations (single-price evaluation,
  no survivorship adjustment, fixed thresholds).
- Every number and rule in EVALUATION.md was transcribed directly from
  backend/services/accuracy_tracker.py and
  backend/agents/portfolio_manager.py, and every worked-example
  percentage was independently recomputed by hand.

## Testing
Docs-only change -- no backend/ or frontend/ files touched, so neither
CI job has anything new to check. Verified manually: every internal
doc link resolves, `git diff --stat` against main shows only the two
docs files (plus this task's own workflow doc), and the badge/table
Markdown was checked in a rendered preview.

## LangSmith Trace
N/A -- no agent, prompt, or LLM-facing code touched.

## Screenshots
_Attach a screenshot of the rendered README (showing both badges) here
before opening the PR._

## Related Issues
Closes #93
```

## Testing

This task has no automated test coverage of its own — it is a documentation-only
change, and neither CI job (`backend`, `frontend`) is configured to lint or check
Markdown outside `frontend/`. Verification is manual:

- **Link resolution** — `docs/EVALUATION.md` exists at the path the new README table
  row links to; every anchor in `EVALUATION.md`'s own Table of Contents resolves to a
  real heading in the same file.
- **Scope check** — `git diff --stat main` shows only `README.md`,
  `docs/EVALUATION.md`, and this workflow doc; nothing under `backend/` or
  `frontend/` changed.
- **Numeric accuracy** — every worked-example percentage in `EVALUATION.md` §5 was
  independently recomputed by hand against the real formula
  (`(price_later - price_at_verdict) / price_at_verdict * 100`) and cross-checked
  against `score_directional_correctness`'s actual boundary rule
  (`price_change_pct <= -DEAD_ZONE_PCT` / `>= DEAD_ZONE_PCT`) before being written down.
- **Rendered Markdown** — the badge line, the Documentation table, and
  `EVALUATION.md`'s own tables were checked in a rendered Markdown preview to confirm
  no broken table alignment or malformed link syntax.

## Verification gate run locally before pushing

Backend and frontend gates are both unaffected by this task (no files under either
directory changed), so neither needs to be re-run, but for completeness this is what
CI itself would run:

```bash
# Backend job (unaffected -- no backend/ files in this PR)
set ENVIRONMENT=test
python -m black backend
python -m isort backend
python -m flake8 backend
python -m mypy backend
python -m pytest backend/tests/unit -v

# Frontend job (unaffected -- no frontend/ files in this PR)
cd frontend
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
```

## LangSmith Trace

N/A — no agent, prompt, or LLM-facing code touched; this task adds documentation only.

## Related Issues

Closes #93 (adjust to your actual issue number if different).