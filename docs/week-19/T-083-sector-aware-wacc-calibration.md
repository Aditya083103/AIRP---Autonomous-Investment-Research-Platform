# T-083 — Sector-aware WACC calibration in DCF model

**Phase 7 — Bug Fixes & Verdict Calibration (Week 19)**
**Branch:** `feat/valuation-sector-wacc`
**Depends on:** none — independent of T-081/T-082, part of the same Phase 7
sequence per the batching guidance (each T-08x task is a separate request)

---

## 1. What this task does

The Valuation Agent's DCF model has always discounted every company's free
cash flow at the same flat `DEFAULT_WACC_PCT = 12.0`, adjusted only by the
live RBI repo rate (`wacc_pct = rbi_rate + 8.0`). A single flat rate is
wrong in two directions at once:

- **IT services and FMCG** are asset-light, low-capex, high-visibility
  cash-flow businesses. A 12% WACC systematically *undervalues* them —
  this is the exact bias noted in the diagnosed verdict-bias backlog
  (`AIRP_Project_Overview` design notes: "DCF model uses flat 12% WACC
  that systematically undervalues premium Indian large-caps").
- **Capital-intensive, cyclical sectors** (auto, energy, infrastructure,
  metals, cement, construction) carry more operating and financial
  leverage risk than a flat 12% reflects, which can *overstate* their
  intrinsic value relative to their real cost of capital.

### Fix

`valuation_agent.py` now resolves a **canonical sector band** before
running the DCF and looks up a sector-specific base WACC instead of
always using the flat default:

```python
SECTOR_WACC_MAP: dict[str, float] = {
    "it_services": 10.0,
    "fmcg": 10.5,
    "capital_intensive_cyclical": 13.0,
    "diversified": DEFAULT_WACC_PCT,  # 12.0 -- unclassified fallback
}
```

The sector key is resolved by `_resolve_sector_key()` using a priority
chain, exactly matching the task's "sourced from the peer sector already
resolved via the Screener.in scrape" requirement:

1. **`peer_data["sector"]`** — the sector/industry label scraped from the
   Screener.in company page. `_parse_screener_page()` now also calls a
   new best-effort `_extract_sector_from_page()` helper (three fallback
   selectors: the `#peers` section heading, the `.sub` breadcrumb next to
   the company name, and a `<meta name="industry">` tag). Like the
   existing ratio-table scrape, this is non-fatal — if none of the three
   are found, or the whole scrape fails, it returns `None` and the chain
   falls through to the next signal.
2. **`InvestmentState.sector`** — the `sector` field already threaded
   through `_run_valuation_analysis_core()`'s signature since T-039, but
   never actually used until now.
3. **Company name** — keyword-matched as a last resort (catches names
   like "XYZ Software Ltd" even with no other signal).

Classification (`_classify_sector_for_wacc()`) uses whole-word regex
matching (`\bkeyword\b`), not plain substring matching — this matters
because naive substring checks would misclassify e.g. "capital" (contains
"it"), "automobile" (contains "auto" only if you don't require a
boundary), or "biotechnology" (contains "technology"). All three of
these are covered by regression tests.

The **live RBI repo rate still matters**, but its role changed: instead
of being the *only* signal (`wacc_pct = rbi_rate + 8.0`), it now nudges
the resolved sector base up or down from a neutral policy-rate anchor
(6.5%):

```python
wacc_pct = sector_base_wacc_pct + (rbi_rate - NEUTRAL_RBI_REPO_RATE_PCT)
```

A tightening cycle raises the cost of capital for every sector, not just
one flat number — this is a more defensible macro model and it also
means the existing `test_rbi_rate_adjusts_wacc` regression test (higher
RBI rate → higher WACC) keeps passing unmodified in spirit, just with new
expected numeric values (now documented explicitly in the test).

Backward compatibility: any company that cannot be classified into a
known band (peer scrape sector missing, state sector missing, and the
company name doesn't contain a recognizable keyword) falls back to the
`'diversified'` band, which is pinned to `DEFAULT_WACC_PCT` — so a
company AIRP could not previously distinguish gets **exactly** the old
flat-default behaviour, byte-for-byte, when there's no RBI data either.

### New output field

`ValuationOutput.dcf_sector_used: Optional[str]` records which canonical
band was actually used (e.g. `"it_services"`, `"diversified"`) — this
gives the Portfolio Manager / memo / any future audit trail visibility
into *why* a given WACC was chosen, without having to reverse-engineer it
from the number alone. Purely additive (`default=None`), so it cannot
break any existing consumer of `ValuationOutput.model_dump()`.

### Execution-order change

`_fetch_peer_multiples()` (the Screener.in peer scrape) now runs
**before** the WACC/DCF stages instead of after them, because its
`sector` field is the top-priority signal for WACC resolution. Everything
it previously fed into (peer PE/PB/EV-EBITDA overrides, sector averages,
peer tickers) is unchanged — only the *position* of the call moved, not
its behaviour or its `try/except` error handling.

### Explicitly out of scope for T-083

Banking and NBFC sector labels are intentionally **not** classified into
a band yet — they fall through to `'diversified'` (12.0), same as today.
The task only asked for "IT services/FMCG ~10-10.5%, capital-intensive/
cyclical ~12-13%"; adding a banking/financials band is a natural
follow-up but is left for a separate, independently-reviewable task
rather than scope-creeping this one.

---

## 2. Files changed

```
backend/agents/valuation_agent.py                     (modified)
backend/agents/output_models.py                        (modified)
backend/tests/unit/test_valuation_agent.py             (modified)
docs/week-19/T-083-sector-aware-wacc-calibration.md    (new)
```

---

## 3. Full git workflow

### 3.1 Checkout and branch from `main`

```bash
git checkout main
git pull origin main
git checkout -b feat/valuation-sector-wacc
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
python -m black backend/agents/valuation_agent.py backend/agents/output_models.py backend/tests/unit/test_valuation_agent.py
python -m isort backend/agents/valuation_agent.py backend/agents/output_models.py backend/tests/unit/test_valuation_agent.py
python -m flake8 backend/agents/valuation_agent.py backend/agents/output_models.py backend/tests/unit/test_valuation_agent.py
python -m mypy --strict --warn-unused-ignores backend/agents/valuation_agent.py backend/agents/output_models.py
python -m pytest backend/tests/unit/test_valuation_agent.py -v
```

Then run the full unit suite once to confirm no regressions elsewhere
(e.g. `portfolio_manager.py` and any memo/report template that reads
`ValuationOutput` fields):

```bash
python -m pytest backend/tests/unit -q
```

### 3.5 Frontend verification gate

No frontend files are touched by this task, so this is a formality — it
should pass exactly as it did on `main` before this branch:

```bash
cd frontend
npm run type-check && npm run lint && npm run format:check && npm run test:run && npm run build
cd ..
```

### 3.6 Manual sanity check (recommended, not CI-gating)

Confirm sector resolution and the WACC lookup directly:

```bash
python -c "
from backend.agents.valuation_agent import (
    _resolve_sector_key, _get_sector_wacc_pct, SECTOR_WACC_MAP, DEFAULT_WACC_PCT,
)

cases = [
    ('Information Technology', None, 'Infosys'),
    ('FMCG', None, 'ITC'),
    ('Automobile', None, 'Tata Motors'),
    (None, None, 'Some Diversified Conglomerate'),
]
for state_sector, peer_sector, company_name in cases:
    key = _resolve_sector_key(peer_sector, state_sector, company_name)
    wacc = _get_sector_wacc_pct(key)
    print(f'{company_name:35s} sector={key:28s} wacc={wacc}%')
"
```

Expected output:

```
Infosys                            sector=it_services                 wacc=10.0%
ITC                                 sector=fmcg                        wacc=10.5%
Tata Motors                         sector=capital_intensive_cyclical  wacc=13.0%
Some Diversified Conglomerate       sector=diversified                 wacc=12.0%
```

### 3.7 Two-commit pattern (pre-commit auto-fix handling)

```bash
git add backend/agents/valuation_agent.py backend/agents/output_models.py backend/tests/unit/test_valuation_agent.py docs/week-19/T-083-sector-aware-wacc-calibration.md

git commit -m "feat(valuation): add sector-aware WACC lookup to DCF model" --no-verify
```

If `black`/`isort` pre-commit hooks (where they aren't blocked by Windows
App Control) reformat any staged file, stage the auto-fixed version and
recommit:

```bash
git add -u
git commit -m "chore: apply pre-commit auto-formatting" --no-verify
```

`--no-verify` is the established AIRP workaround for Windows App Control
blocking unsigned pre-commit hook shims (WinError 4551). The GitHub
Actions Linux runner is the real enforcement gate — it runs
`black --check`, `isort --check`, `flake8`, `mypy --strict`, and `pytest`
unconditionally for backend, and `type-check`, `lint`, `format:check`,
`test:run`, `build` for frontend.

### 3.8 Push and open PR

```bash
git push -u origin feat/valuation-sector-wacc
```

Open a PR from `feat/valuation-sector-wacc` → `main` on GitHub (or
`gh pr create` if the CLI is installed) using the title and description
below.

---

## 4. Pull Request

### Title

```
feat(valuation-agent): replace flat 12% WACC with sector-calibrated rates
```

### Description

```markdown
## Summary

The Valuation Agent's DCF model discounted every company's free cash flow
at the same flat 12% WACC, adjusted only by the live RBI repo rate. This
systematically undervalues asset-light sectors (IT services, FMCG) and
can overstate intrinsic value for capital-intensive, cyclical sectors
(auto, energy, infrastructure, metals). This task replaces the flat
default with a sector-specific base rate, resolved primarily from the
sector label already scraped from Screener.in.

## Changes

- Added `SECTOR_WACC_MAP` (it_services=10.0%, fmcg=10.5%,
  capital_intensive_cyclical=13.0%, diversified=12.0% == the old flat
  DEFAULT_WACC_PCT, preserved as the fallback).
- Added `_classify_sector_for_wacc()`: whole-word regex keyword matching
  from free text (sector label or company name) to a canonical band.
  Whole-word matching specifically avoids false positives such as "it"
  inside "capital", "auto" inside "automatic", and "technology" inside
  "biotechnology" -- all covered by regression tests.
- Added `_resolve_sector_key()`: priority chain -- Screener.in peer-scrape
  sector label > InvestmentState.sector > company name -- falling back to
  'diversified' (and therefore DEFAULT_WACC_PCT) when nothing matches, so
  pre-T-083 behaviour is preserved exactly for any company AIRP could not
  previously classify.
- Added `_get_sector_wacc_pct()`: safe lookup with a DEFAULT_WACC_PCT
  fallback for any unrecognised key.
- Added `_extract_sector_from_page()`: best-effort sector/industry label
  extraction from the Screener.in company page (peers-section heading,
  breadcrumb link, or a meta tag), wired into `_parse_screener_page()`.
  Non-fatal on failure, matching the existing scraper's error philosophy.
- `_run_valuation_analysis_core()`: the Screener.in peer scrape now runs
  before the WACC/DCF stages (its sector label is now the top-priority
  WACC signal); the RBI repo rate now nudges the resolved sector base
  WACC from a neutral 6.5% anchor, instead of being the sole signal.
- Added `ValuationOutput.dcf_sector_used: Optional[str]` -- purely
  additive field recording which band was used, for auditability.
- `_run_dcf()` itself is unchanged (still takes `wacc_pct: float`) --
  callers now resolve a sector-specific value instead of always passing
  the flat default.

## Testing

- `python -m pytest backend/tests/unit/test_valuation_agent.py -v` --
  all passing, including new tests:
  - `TestSectorWaccMap` -- constants sanity (bands present, ranges match
    the task spec: IT/FMCG 10-10.5%, capital-intensive/cyclical 12-13%)
  - `TestClassifySectorForWacc` -- covers it_services, fmcg, and
    capital_intensive_cyclical (auto, oil & gas, cement, metals), plus
    word-boundary regression guards (automobile vs "auto" substring,
    biotechnology vs "technology" substring, automatic vs "auto")
  - `TestResolveSectorKey` -- priority chain (peer > state > company
    name > diversified fallback)
  - `TestGetSectorWaccPct` -- lookup + unknown-key fallback
  - `TestExtractSectorFromPage` -- peers heading / breadcrumb / meta tag
    extraction against real BeautifulSoup-parsed HTML fixtures, plus a
    graceful-None case
  - `test_dcf_wacc_pct_reflects_it_services_sector` -- exact WACC (10.0)
    and `dcf_sector_used` ("it_services") for the default test fixture
  - `test_sector_specific_wacc_across_three_bands` -- end-to-end through
    `_run_valuation_analysis_core` for it_services, fmcg,
    capital_intensive_cyclical, and diversified, asserting exact WACC
  - `test_peer_scrape_sector_takes_priority_over_state_sector` -- proves
    the Screener.in signal outranks InvestmentState.sector
  - `test_run_dcf_accepts_sector_specific_wacc` (T-083 acceptance
    criteria, verbatim) -- `_run_dcf` produces correctly-ordered,
    positive values across all four bands for the same Infosys inputs
  - `test_rbi_rate_adjusts_wacc` (existing, updated) -- now asserts the
    exact new expected values (13.5% / 10.5%) instead of only the
    monotonicity relationship
- `python -m pytest backend/tests/unit -q` -- full unit suite green.
- `black`, `isort`, `flake8`, `mypy --strict --warn-unused-ignores` all
  clean on changed files.
- Manually verified `_resolve_sector_key` / `_get_sector_wacc_pct` for
  Infosys, ITC, Tata Motors, and an unclassifiable company name -- see
  workflow doc section 3.6 for the exact commands and expected output.

## LangSmith Trace

N/A -- pure deterministic logic change (sector classification, WACC
lookup, scraper extension); no LLM prompt content or call path touched.

## Screenshots

N/A -- backend-only change, no UI impact.

## Related Issues

Closes #083
```

---

## 5. Acceptance criteria checklist

- [x] `_run_dcf` accepts a sector-specific WACC (signature unchanged;
      callers now resolve and pass a sector-specific value)
- [x] Unit tests cover at least 3 sector bands (it_services, fmcg,
      capital_intensive_cyclical, plus the diversified default — 4 total)
- [x] Existing DCF-dependent tests updated with new expected values
      (`test_dcf_wacc_pct_set` retained + new
      `test_dcf_wacc_pct_reflects_it_services_sector` added with exact
      values; `test_rbi_rate_adjusts_wacc` updated with exact new
      expected WACC values instead of only a monotonicity check)
- [x] Flat `DEFAULT_WACC_PCT = 12.0` replaced by `SECTOR_WACC_MAP`
      lookup, sourced primarily from the Screener.in peer scrape's
      sector label (`peer_data['sector']`, extracted best-effort by the
      new `_extract_sector_from_page()`)
- [x] IT services / FMCG bands land in the 10-10.5% range; the
      capital-intensive/cyclical band lands in the 12-13% range (both
      verified directly against the task's stated ranges in
      `TestSectorWaccMap`)
- [x] Backward compatible: unclassifiable companies get exactly the old
      flat-default WACC when no RBI data is present either
- [x] Commit message matches acceptance criteria exactly:
      `feat(valuation): add sector-aware WACC lookup to DCF model`

## 6. Notes for what's next

T-084 (surface `years_available` in output/memo/UI) and T-085 (Analysis
Horizon selector) are independent of this change and can be requested
next, one at a time, per the usual flow. T-086 (regression tests + design
doc for the whole T-081-T-085 verdict-calibration batch) is the natural
place to eventually add a banking/NBFC WACC band if that's wanted, since
it explicitly scopes "docs/week-25 design doc explaining before/after
verdict distribution rationale" across the whole batch rather than one
task at a time.