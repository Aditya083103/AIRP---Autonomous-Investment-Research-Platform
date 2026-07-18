# T-084 — Surface years_available in output, memo, and UI

**Phase 7 — Bug Fixes & Verdict Calibration (Week 19)**
**Branch:** `feat/surface-years-available`
**Depends on:** none — independent of T-081/T-082/T-083, part of the same
Phase 7 sequence per the batching guidance (each T-08x task is a separate
request)

---

## 1. What this task does

`fetch_financials` has always returned `years_available` (how many of the
last 4 fiscal years yFinance actually had data for) at the top level of
its response — but nothing downstream ever read it. A company with only
2 years of listed history looked identical, on the memo and in the UI, to
one with a full 4-year track record, even though the Fundamental
Analyst's score, trends, and every downstream agent that reads
`state["fundamental"]` were working with half the data.

This task threads that single existing number through three layers that
previously dropped it on the floor, ending in a small, honest
"based on N of 4 years" caveat that only appears when it's actually
needed.

### Layer 1 — `FundamentalAnalysis` schema pass-through

- `output_models.FundamentalAnalysis` gains `years_available: Optional[int]`
  (`ge=0, le=4`, default `None`) — grouped next to `data_quality`, since
  the two are related but distinct: `data_quality` measures how many of
  the 5 *scoring* metrics could be computed; `years_available` is the raw
  count of fiscal years the fetch itself returned, independent of
  whether enough of them had usable numbers to score.
- `fundamental_analyst._run_fundamental_analysis_core()` extracts
  `financials.get("years_available")` in Step 4 (right next to the other
  supplementary field extractions) and passes it straight through to the
  constructed `FundamentalAnalysis`. When the financials fetch fails
  entirely, Step 1's error-fallback stub dict has no `years_available`
  key at all — so `years_available` correctly comes out `None` in that
  case (there's no year count to report), not a fabricated `0`.

### Layer 2 — Investment Memo (PDF) template

- `memo_generator._build_data_completeness_note(years_available)` is a
  new pure helper: returns an italic Markdown note
  (`*Fundamental analysis based on N of 4 fiscal years of available
  financial data.*`) when `0 <= years_available < 4`, and `None` — so
  nothing renders — when `years_available` is `None`, negative, or `>= 4`.
- `_build_header_section()` gained an optional `data_completeness_note`
  parameter, inserted as its own line between the recommendation table
  and the `---` divider, so it sits in the "at a glance" area of the memo
  alongside verdict/conviction/price target, not buried in a numbered
  section.
- `generate_investment_memo(state)` now also reads
  `state.get("fundamental")` (previously completely unused by this
  module, mirroring exactly the same "parameter threaded through but
  never read" shape T-083 found and fixed for `valuation_agent`'s
  `sector` field) and passes `fundamental.get("years_available")` into
  `_build_memo_markdown()`. No changes were needed in `pdf_export.py` —
  the note is plain italic-text Markdown, a construct its hand-rolled
  Markdown→HTML converter already handles identically to the existing
  disclaimer section.

### Layer 3 — MemoPage.tsx (frontend UI)

MemoPage renders `InvestmentDecisionResponse` (the Portfolio Manager's
decision), which has no `fundamental` sub-object at all — so surfacing
`years_available` here required extending the API response, not just the
frontend component:

- `AnalysisResultData` (backend/services/analysis.py) gains
  `fundamental_years_available: Optional[int] = None` — the one field on
  that dataclass sourced from `state_snapshot["fundamental"]` rather than
  `["decision"]`, extracted by a new sibling helper
  `_extract_fundamental_years_available_from_snapshot()` (mirrors
  `_extract_decision_from_snapshot()`'s exact shape: parse once via the
  shared `_parse_state_snapshot()`, pick one key back out). Unlike a
  missing `decision`, a missing/malformed `fundamental` entry is a soft
  signal — it never raises `AnalysisNotReadyError`, it just comes back
  `None`.
- `InvestmentDecisionResponse` (backend/models/schemas.py) gains the same
  field, with its docstring explicitly calling out that this is the one
  deliberate exception to its stated "field-for-field identical to
  InvestmentDecision" contract.
- The router (`GET /api/v1/analysis/{job_id}/result`) passes
  `fundamental_years_available=result.fundamental_years_available`
  through unchanged.
- The frontend `InvestmentDecisionResponse` type (types/analysis.ts)
  mirrors the new field as `fundamental_years_available: number | null`.
- `MemoPage.tsx` computes the note once via a new
  `formatDataCompletenessNote()` helper — deliberately mirroring
  `_build_data_completeness_note()`'s thresholds exactly (`null` or
  `>= 4` → no note) so the PDF and the page can never disagree on when
  to show it — and renders it as a small italic line directly under the
  "Generated ..." timestamp, with `data-testid="data-completeness-note"`
  for testability.

### Why the API field is unconditional but the UI/PDF note is conditional

`fundamental_years_available` always round-trips through the API
response, including when it's `4` — the endpoint's job is to report the
fact accurately, not to decide when it's interesting. The "no note when
4/4" behavior (the acceptance criterion) lives entirely in the two
*presentation* layers (`_build_data_completeness_note` for the PDF,
`formatDataCompletenessNote` for the page), which is the correct place
for a "don't show me trivia" decision — not baked into the data contract
itself.

---

## 2. Files changed

```
backend/agents/output_models.py                                (modified)
backend/agents/fundamental_analyst.py                           (modified)
backend/services/memo_generator.py                              (modified)
backend/services/analysis.py                                    (modified)
backend/models/schemas.py                                       (modified)
backend/routers/analysis.py                                     (modified)
backend/tests/unit/test_output_models.py                        (modified)
backend/tests/unit/test_fundamental_analyst.py                  (modified)
backend/tests/unit/test_memo_generator.py                       (modified)
backend/tests/unit/test_analysis_result_history_service.py      (modified)
backend/tests/unit/test_analysis_result_history_router.py       (modified)
frontend/src/types/analysis.ts                                  (modified)
frontend/src/pages/MemoPage.tsx                                 (modified)
frontend/src/test/MemoPage.test.tsx                             (modified)
frontend/src/test/winnerLogic.test.ts                           (modified)
frontend/src/test/ResultsPanel.test.tsx                         (modified)
frontend/src/test/VerdictPanel.test.tsx                         (modified)
docs/week-19/T-084-surface-years-available.md                   (new)
```

The three `frontend/src/test/*.ts(x)` changes outside `MemoPage.test.tsx`
are one-line additions each (`fundamental_years_available: null,`) to
local `makeDecision()` test factories that are explicitly typed
`InvestmentDecisionResponse` — required for `npm run type-check` to pass
now that the field is non-optional on that type, not a behavioural
change to those tests.

---

## 3. Full git workflow

### 3.1 Checkout and branch from `main`

Make sure T-083 is merged to `main` first (this branch was cut from a
tree that already has `dcf_sector_used` etc. — not a hard dependency,
just the expected linear history for Phase 7).

```bash
git checkout main
git pull origin main
git checkout -b feat/surface-years-available
```

### 3.2 Apply the changed files

Copy the delivered files into your working tree at the same paths shown
in section 2 above (overwrite the existing ones).

### 3.3 Set up environment for local verification

```bash
# Windows Git Bash — do NOT chain with && (adds a trailing space to the value)
set ENVIRONMENT=test
```

### 3.4 Backend verification gate (must all pass, in order)

```bash
python -m black backend/agents/output_models.py backend/agents/fundamental_analyst.py backend/services/memo_generator.py backend/services/analysis.py backend/models/schemas.py backend/routers/analysis.py backend/tests/unit/test_output_models.py backend/tests/unit/test_fundamental_analyst.py backend/tests/unit/test_memo_generator.py backend/tests/unit/test_analysis_result_history_service.py backend/tests/unit/test_analysis_result_history_router.py

python -m isort backend/agents/output_models.py backend/agents/fundamental_analyst.py backend/services/memo_generator.py backend/services/analysis.py backend/models/schemas.py backend/routers/analysis.py backend/tests/unit/test_output_models.py backend/tests/unit/test_fundamental_analyst.py backend/tests/unit/test_memo_generator.py backend/tests/unit/test_analysis_result_history_service.py backend/tests/unit/test_analysis_result_history_router.py

python -m flake8 backend/agents/output_models.py backend/agents/fundamental_analyst.py backend/services/memo_generator.py backend/services/analysis.py backend/models/schemas.py backend/routers/analysis.py backend/tests/unit/test_output_models.py backend/tests/unit/test_fundamental_analyst.py backend/tests/unit/test_memo_generator.py backend/tests/unit/test_analysis_result_history_service.py backend/tests/unit/test_analysis_result_history_router.py

python -m mypy --strict --warn-unused-ignores backend/agents/output_models.py backend/agents/fundamental_analyst.py backend/services/memo_generator.py backend/services/analysis.py backend/models/schemas.py backend/routers/analysis.py

python -m pytest backend/tests/unit/test_output_models.py backend/tests/unit/test_fundamental_analyst.py backend/tests/unit/test_memo_generator.py backend/tests/unit/test_analysis_result_history_service.py backend/tests/unit/test_analysis_result_history_router.py -v
```

Then run the full unit suite once to confirm no regressions elsewhere
(portfolio_manager.py, risk_officer.py, and any other consumer of
`state["fundamental"]` or `InvestmentDecisionResponse`):

```bash
python -m pytest backend/tests/unit -q
```

### 3.5 Frontend verification gate

```bash
cd frontend
npm run type-check
npm run lint
npm run format:check
npm run test:run
npm run build
cd ..
```

`type-check` is the one most likely to catch something here: three test
factories (`winnerLogic.test.ts`, `ResultsPanel.test.tsx`,
`VerdictPanel.test.tsx`) construct object literals explicitly typed
`InvestmentDecisionResponse`, so making `fundamental_years_available`
non-optional on that interface required adding it to each — already done
in the delivered files, called out here so a `type-check` failure on a
*different*, not-yet-updated factory elsewhere in the tree is easy to
recognise as the same class of fix rather than a real regression.

### 3.6 Manual sanity check (recommended, not CI-gating)

Confirm the data-completeness note logic directly, backend side:

```bash
python -c "
from backend.services.memo_generator import _build_data_completeness_note

for years in (None, 0, 1, 2, 3, 4, 5, -1):
    print(f'years_available={years!r:>6} -> note={_build_data_completeness_note(years)!r}')
"
```

Expected output:

```
years_available=None   -> note=None
years_available=0      -> note='*Fundamental analysis based on 0 of 4 fiscal years of available financial data.*'
years_available=1      -> note='*Fundamental analysis based on 1 of 4 fiscal years of available financial data.*'
years_available=2      -> note='*Fundamental analysis based on 2 of 4 fiscal years of available financial data.*'
years_available=3      -> note='*Fundamental analysis based on 3 of 4 fiscal years of available financial data.*'
years_available=4      -> note=None
years_available=5      -> note=None
years_available=-1     -> note=None
```

And end-to-end through the memo assembly:

```bash
python -c "
from backend.services.memo_generator import generate_investment_memo

decision = {
    'verdict': 'BUY', 'conviction_score': 8, 'time_horizon': '12 months',
    'executive_summary': 'Strong fundamentals.', 'summary': 'BUY, conviction 8/10.',
}
state = {
    'job_id': 'demo', 'company_name': 'Demo Corp', 'ticker': 'DEMO.NS',
    'decision': decision, 'fundamental': {'years_available': 2},
}
memo = generate_investment_memo(state)['memo_markdown']
print('based on 2 of 4' in memo.split(chr(10), 15)[0:15])
print([l for l in memo.splitlines() if 'fiscal years' in l])
"
```

Expected: the last line prints something like
`['*Fundamental analysis based on 2 of 4 fiscal years of available financial data.*']`.

### 3.7 Two-commit pattern (pre-commit auto-fix handling)

```bash
git add backend/agents/output_models.py backend/agents/fundamental_analyst.py backend/services/memo_generator.py backend/services/analysis.py backend/models/schemas.py backend/routers/analysis.py backend/tests/unit/test_output_models.py backend/tests/unit/test_fundamental_analyst.py backend/tests/unit/test_memo_generator.py backend/tests/unit/test_analysis_result_history_service.py backend/tests/unit/test_analysis_result_history_router.py frontend/src/types/analysis.ts frontend/src/pages/MemoPage.tsx frontend/src/test/MemoPage.test.tsx frontend/src/test/winnerLogic.test.ts frontend/src/test/ResultsPanel.test.tsx frontend/src/test/VerdictPanel.test.tsx docs/week-19/T-084-surface-years-available.md

git commit -m "feat(memo): surface fundamental data-years-available to user" --no-verify
```

If `black`/`isort`/`prettier` pre-commit hooks (where they aren't blocked
by Windows App Control) reformat any staged file, stage the auto-fixed
version and recommit:

```bash
git add -u
git commit -m "chore: apply pre-commit auto-formatting" --no-verify
```

`--no-verify` is the established AIRP workaround for Windows App Control
blocking unsigned pre-commit hook shims (WinError 4551). The GitHub
Actions Linux runner is the real enforcement gate — it runs
`black --check`, `isort --check`, `flake8`, `mypy --strict`, and
`pytest` for backend, and `type-check`, `lint`, `format:check`,
`test:run`, `build` for frontend, unconditionally.

### 3.8 Push and open PR

```bash
git push -u origin feat/surface-years-available
```

Open a PR from `feat/surface-years-available` → `main` on GitHub (or
`gh pr create` if the CLI is installed) using the title and description
below.

---

## 4. Pull Request

### Title

```
feat(memo,frontend): show years of financial history used in each analysis
```

### Description

```markdown
## Summary

fetch_financials has always returned years_available (how many of the
last 4 fiscal years yFinance had data for) but nothing downstream ever
read it -- a company with 2 years of history looked identical to one
with a full 4-year track record on the memo and in the UI. This task
threads that number through three layers -- the FundamentalAnalysis
schema, the Investment Memo (PDF) template, and MemoPage.tsx -- ending
in a small "based on N of 4 years" caveat that only appears when the
data is genuinely partial.

## Changes

- `output_models.FundamentalAnalysis`: new `years_available: Optional[int]`
  field (ge=0, le=4), pass-through from `fetch_financials`'s existing
  top-level count. Distinct from `data_quality` (T-081), which measures
  scoring-metric completeness, not fiscal-year count.
- `fundamental_analyst._run_fundamental_analysis_core()`: extracts
  `years_available` from the financials dict; None when the fetch failed
  entirely (no stub `years_available` key in that fallback path).
- `memo_generator`: new `_build_data_completeness_note()` pure helper
  (note when 0 <= years_available < 4, None -- i.e. no note -- otherwise);
  `_build_header_section()` renders it inline with the recommendation
  table; `generate_investment_memo()` now reads `state["fundamental"]`
  (previously unused by this module) to supply it. No pdf_export.py
  changes needed -- the note is plain italic Markdown, already supported.
- `AnalysisResultData` / `get_analysis_result()`
  (backend/services/analysis.py): new `fundamental_years_available`
  field, extracted from the same `state_snapshot`'s `fundamental` entry
  by a new sibling helper to `_extract_decision_from_snapshot()`. Unlike
  a missing decision, a missing/malformed fundamental entry is a soft
  signal -- it never raises AnalysisNotReadyError.
- `InvestmentDecisionResponse` (backend/models/schemas.py): new
  `fundamental_years_available: Optional[int]` field -- the one
  deliberate exception to this schema's stated "field-for-field
  identical to InvestmentDecision" contract, documented as such.
- Router: passes `result.fundamental_years_available` through unchanged.
- Frontend `InvestmentDecisionResponse` type: mirrors the new field as
  `number | null`.
- `MemoPage.tsx`: new `formatDataCompletenessNote()` helper, deliberately
  mirroring `_build_data_completeness_note()`'s exact thresholds so the
  PDF and the page never disagree on when to show the note; rendered
  under the "Generated ..." timestamp with
  `data-testid="data-completeness-note"`.
- Three existing frontend test factories that explicitly type their
  return as `InvestmentDecisionResponse` (winnerLogic.test.ts,
  ResultsPanel.test.tsx, VerdictPanel.test.tsx) updated with
  `fundamental_years_available: null` to keep `npm run type-check` green
  now that the field is required (though nullable) on the interface.

## Testing

- `python -m pytest backend/tests/unit/test_output_models.py backend/tests/unit/test_fundamental_analyst.py backend/tests/unit/test_memo_generator.py backend/tests/unit/test_analysis_result_history_service.py backend/tests/unit/test_analysis_result_history_router.py -v`
  -- all passing, including new tests:
  - `TestFundamentalAnalysis`: years_available default/settable/bounds
    (0-4 inclusive)
  - `TestRunFundamentalAnalysisCore`: full-data (4), partial-data (2),
    and fetch-failure (None) pass-through
  - `TestBuildDataCompletenessNote`: None/0/partial/4/negative/>4 inputs
  - `TestBuildHeaderSection` / `TestBuildMemoMarkdown`: note
    included/omitted at both the header and full-assembly level
  - `TestGenerateInvestmentMemoNode`: state["fundamental"]["years_available"]
    reaches the rendered memo; missing/non-dict fundamental never raises
  - `TestGetAnalysisResultFundamentalYearsAvailable`: extraction from
    state_snapshot, including string-coercion and malformed-value cases,
    and confirms a missing fundamental entry never blocks a successful
    result
  - `TestGetResultSuccess` (router): fundamental_years_available present,
    null, and full-4 round-trip through the real HTTP response
- `python -m pytest backend/tests/unit -q` -- full unit suite green.
- `npm run test:run` -- including new MemoPage.test.tsx cases: note shown
  for partial years, hidden for 4/4, hidden for null, correct wording
  for a single year.
- `black`, `isort`, `flake8`, `mypy --strict --warn-unused-ignores` clean
  on changed backend files; `type-check`, `lint`, `format:check` clean on
  changed frontend files.
- Manually verified `_build_data_completeness_note` across the full
  None/0/1/2/3/4/5/-1 input range and end-to-end through
  `generate_investment_memo` -- see workflow doc section 3.6 for exact
  commands and expected output.

## LangSmith Trace

N/A -- pure deterministic pass-through and formatting logic; no LLM
prompt content or call path touched.

## Screenshots

N/A -- text-only change to the memo header and MemoPage's meta area, no
new components or layout changes to review visually beyond the note
itself, which is exercised by the new MemoPage.test.tsx cases.

## Related Issues

Closes #084
```

---

## 5. Acceptance criteria checklist

- [x] `years_available` visible on the memo PDF -- rendered in
      `_build_header_section()`'s output, which `pdf_export.py` converts
      to PDF unchanged (plain italic Markdown, already supported)
- [x] `years_available` visible on MemoPage -- rendered under the
      "Generated ..." timestamp via `formatDataCompletenessNote()`
- [x] Falls back gracefully when 4/4 years available (no note shown) --
      verified independently at the pure-function level
      (`_build_data_completeness_note(4) is None`,
      `formatDataCompletenessNote(4) === null`), the full-memo-assembly
      level, and the rendered-page level (`MemoPage.test.tsx`'s
      "does not show the note when all 4 years..." case)
- [x] `None`/unknown `years_available` also shows no note (not just the
      literal `4` case) -- both presentation layers treat "unknown" and
      "complete" identically: no caveat either way
- [x] `FundamentalAnalysis` schema pass-through -- `years_available`
      field added and wired through `_run_fundamental_analysis_core()`
- [x] Commit message matches acceptance criteria exactly:
      `feat(memo): surface fundamental data-years-available to user`

## 6. Notes for what's next

T-085 (Analysis Horizon selector) and T-086 (regression tests + design
doc for the T-081-T-085 batch) remain in Phase 7 and can be requested
next, one at a time. T-086's `docs/week-25` design doc is the natural
place to eventually cross-reference this task's before/after memo
presentation alongside T-081's data_quality guard and T-083's sector-WACC
calibration, since all three are part of the same "stop hiding data
quality from the reader" theme even though they landed as independent,
separately-reviewable PRs.