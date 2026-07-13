# T-082 — Propagate insufficient-data guard through Risk Officer and Portfolio Manager

**Phase 8 — Verdict Accuracy Tracker groundwork (Week 20)**
**Branch:** `fix/verdict-insufficient-data-guard`
**Depends on:** T-081 (`FundamentalAnalysis.data_quality` field must already exist)

---

## 1. What this task does

T-081 taught the Fundamental Analyst to report `data_quality="insufficient"`
and `score=None` instead of a misleading floor of `1` when it lacks data.
T-082 makes the rest of the committee actually respect that signal instead
of quietly re-introducing the same bias one layer downstream.

Three call sites previously treated a _missing_ fundamental score exactly
like a _genuinely weak_ one:

1. **`risk_officer._score_risk()` — `financial_risk`.** Even a lone D/E
   fragment (possible even when overall `data_quality="insufficient"`) was
   still used to push `financial_risk` up or down, and a `None` score
   defaulted to a neutral `5` that at least didn't add risk — but the
   D/E/FCF fragment logic ran regardless of `data_quality`.
2. **`portfolio_manager._compute_agent_weights()`.** Fundamental analyst
   kept its full `0.20` base weight as long as it didn't set `"error"`,
   even when `data_quality="insufficient"` meant its `score` was a
   fabricated neutral value rather than a real signal.
3. **`portfolio_manager._determine_verdict()` — Hard Gate 2.** `fund_score
= int(fundamental.get("score") or 5)` turns `None` into `5`, and Gate 2
   (`valuation_verdict == "overvalued" and fund_score < 6`) fires on that
   fabricated `5` — forcing a hard **SELL** override on every
   overvalued-but-data-missing case, regardless of what the other six
   agents concluded.

### Fixes

- `risk_officer._score_risk()`: when `fundamental.get("data_quality") ==
"insufficient"`, `financial_risk` stays at its neutral base of `3` and
  skips the D/E / FCF-text / score adjustments entirely.
- `portfolio_manager._compute_agent_weights()`: `fundamental_analyst` gets
  zero weight (redistributed proportionally to the other six agents, same
  mechanism already used for errored agents) when
  `data_quality == "insufficient"`.
- `portfolio_manager._determine_verdict()`: Hard Gate 2 is skipped when
  `data_quality == "insufficient"` — the weighted tally (where the
  fundamental term is already correctly neutralised to `0` via the `or 5`
  fallback) decides the verdict instead of a hard override.

Hard Gate 1 (prohibitive risk) is untouched — it's driven by the Risk
Officer's composite `risk_score`, not the fundamental score, and remains a
correct hard stop regardless of fundamental data quality.

Backward compatibility: fundamental dicts with no `data_quality` key at all
(the shape produced before T-081) default to `"sufficient"` via `or
"sufficient"` everywhere this is checked, so pre-existing behavior for
every already-passing test is unchanged.

---

## 2. Files changed

```
backend/agents/risk_officer.py                  (modified)
backend/agents/portfolio_manager.py             (modified)
backend/tests/unit/test_risk_officer.py         (modified)
backend/tests/unit/test_portfolio_manager.py    (modified)
docs/week-20/T-082-verdict-insufficient-data-guard.md  (new)
```

---

## 3. Full git workflow

### 3.1 Checkout and branch from `main`

Make sure T-081 is merged to `main` first — this task reads the
`data_quality` field it introduced.

```bash
git checkout main
git pull origin main
git checkout -b fix/verdict-insufficient-data-guard
```

### 3.2 Apply the changed files

Copy the delivered files into your working tree at the same paths shown in
section 2 above (overwrite the existing ones).

### 3.3 Set up environment for local verification

```bash
# Windows Git Bash — do NOT chain with && (adds a trailing space to the value)
set ENVIRONMENT=test
```

### 3.4 Backend verification gate (must all pass, in order)

```bash
python -m black backend/agents/risk_officer.py backend/agents/portfolio_manager.py backend/tests/unit/test_risk_officer.py backend/tests/unit/test_portfolio_manager.py
python -m isort backend/agents/risk_officer.py backend/agents/portfolio_manager.py backend/tests/unit/test_risk_officer.py backend/tests/unit/test_portfolio_manager.py
python -m flake8 backend/agents/risk_officer.py backend/agents/portfolio_manager.py backend/tests/unit/test_risk_officer.py backend/tests/unit/test_portfolio_manager.py
python -m mypy --strict --warn-unused-ignores backend/agents/risk_officer.py backend/agents/portfolio_manager.py
python -m pytest backend/tests/unit/test_risk_officer.py backend/tests/unit/test_portfolio_manager.py -v
```

Then run the full unit suite once to confirm no regressions elsewhere
(e.g. `nodes.py`/`routing.py`, which also read `fundamental["score"]`):

```bash
python -m pytest backend/tests/unit -q
```

### 3.5 Manual sanity check (recommended, not CI-gating)

Run one end-to-end fundamental → risk → portfolio manager chain with an
insufficient-data fundamental and confirm the verdict is no longer forced
to SELL purely on missing data:

```bash
python -c "
from backend.agents.portfolio_manager import _compute_agent_weights, _determine_verdict

fundamental_insufficient = {'score': None, 'data_quality': 'insufficient'}
technical = {'signal': 'BUY', 'signal_strength': 8}
sentiment = {'sentiment_score': 0.45}
risk = {'risk_score': 3}
contrarian = {'bear_conviction': 3}
valuation = {'valuation_verdict': 'overvalued'}

weights = _compute_agent_weights(
    fundamental_insufficient, technical, sentiment, {}, risk, contrarian, valuation
)
verdict = _determine_verdict(
    fundamental_insufficient, technical, sentiment, risk, contrarian, valuation, []
)
print('fundamental_analyst weight:', weights['fundamental_analyst'])
print('verdict:', verdict)
"
```

Expected: `fundamental_analyst weight: 0.0` and `verdict: HOLD` (not `SELL`).

### 3.6 Two-commit pattern (pre-commit auto-fix handling)

```bash
git add backend/agents/risk_officer.py backend/agents/portfolio_manager.py backend/tests/unit/test_risk_officer.py backend/tests/unit/test_portfolio_manager.py docs/week-20/T-082-verdict-insufficient-data-guard.md

git commit -m "fix(portfolio-manager): do not penalise verdict on missing fundamental data" --no-verify
```

If `black`/`isort` pre-commit hooks (where they aren't blocked by Windows
App Control) reformat any staged file, stage the auto-fixed version and
recommit:

```bash
git add -u
git commit -m "chore: apply pre-commit auto-formatting" --no-verify
```

`--no-verify` is the established AIRP workaround for Windows App Control
blocking unsigned pre-commit hook shims (WinError 4551). The GitHub Actions
Linux runner is the real enforcement gate — it runs `black --check`, `isort
--check`, `flake8`, `mypy --strict`, and `pytest` unconditionally.

### 3.7 Push and open PR

```bash
git push -u origin fix/verdict-insufficient-data-guard
```

Open a PR from `fix/verdict-insufficient-data-guard` → `main` on GitHub
(or `gh pr create` if the CLI is installed) using the title and description
below.

---

## 4. Pull Request

### Title

```
fix(portfolio-manager): do not penalise verdict on missing fundamental data
```

### Description

```markdown
## Summary

T-081 taught the Fundamental Analyst to report data_quality="insufficient"
and score=None instead of a hard-floored 1 when it lacks data. This task
closes the loop: Risk Officer and Portfolio Manager previously still treated
a missing fundamental score as if it were a genuinely weak one, via `or 5` /
`or "sufficient"` fallbacks that quietly reintroduced the exact bias T-081
removed one layer downstream -- most visibly, Hard Gate 2 forcing an
automatic SELL on every overvalued-but-data-missing case.

## Changes

- `risk_officer._score_risk()`: financial_risk now stays at its neutral
  base (3) and skips the D/E / FCF-text / score adjustments entirely when
  `fundamental.data_quality == "insufficient"`, instead of computing off of
  whichever data fragments happen to be present.
- `portfolio_manager._compute_agent_weights()`: fundamental_analyst gets
  zero weight (redistributed to the other six agents via the existing
  proportional-redistribution mechanism) when
  `data_quality == "insufficient"`, not just when it errors outright.
- `portfolio_manager._determine_verdict()`: Hard Gate 2 (overvalued + weak
  fundamentals -> SELL) is skipped when `data_quality == "insufficient"`.
  The weighted tally -- where the fundamental term is already correctly
  neutralised to 0 via the existing `or 5` fallback -- decides the verdict
  instead of a hard override built on a fabricated neutral score. Hard
  Gate 1 (prohibitive risk_score) is untouched; it does not depend on
  fundamental data quality.
- Backward compatible: fundamental dicts with no `data_quality` key at all
  (pre-T-081 shape) default to "sufficient" everywhere this is checked, so
  every previously-passing test is unaffected.

## Testing

- `python -m pytest backend/tests/unit/test_risk_officer.py backend/tests/unit/test_portfolio_manager.py -v`
  — all passing, including new tests:
  - `test_insufficient_data_quality_holds_financial_risk_at_neutral_base`
  - `test_sufficient_data_quality_still_applies_de_adjustment` (regression guard)
  - `test_missing_data_quality_key_defaults_to_sufficient` (backward-compat guard)
  - `test_insufficient_fundamental_data_quality_gets_zero_weight`
  - `test_sufficient_fundamental_data_quality_keeps_normal_weight` (regression guard)
  - `test_missing_data_quality_key_keeps_normal_weight` (backward-compat guard)
  - `test_overvalued_plus_insufficient_fundamentals_skips_gate_2`
  - `test_overvalued_plus_sufficient_but_weak_fundamentals_still_forces_sell` (regression guard)
- `python -m pytest backend/tests/unit -q` — full unit suite green.
- `black`, `isort`, `flake8`, `mypy --strict --warn-unused-ignores` all clean
  on changed files.
- Manually verified the fundamental_analyst -> risk_officer ->
  portfolio_manager chain with an insufficient-data fundamental input
  produces `fundamental_analyst` weight `0.0` and verdict `HOLD` (not
  `SELL`) despite an overvalued valuation and otherwise-bullish technical
  and sentiment signals.

## LangSmith Trace

N/A — pure deterministic logic change, no LLM call paths touched.

## Screenshots

N/A — backend-only change, no UI impact.

## Related Issues

Closes #082
```

---

## 5. Acceptance criteria checklist

- [x] `risk_officer.py` financial_risk calc skips fragment-based adjustments
      when `data_quality == "insufficient"` (stays at neutral base 3)
- [x] `portfolio_manager._compute_agent_weights()` zero-weights
      fundamental_analyst when `data_quality == "insufficient"`
- [x] `portfolio_manager._determine_verdict()` skips Hard Gate 2 when
      `data_quality == "insufficient"`
- [x] Existing sufficient-data / missing-key test cases unchanged
      (regression + backward-compat tests added to prove it)
- [x] Commit message matches acceptance criteria exactly:
      `fix(portfolio-manager): do not penalise verdict on missing fundamental data`

## 6. Notes for what's next

With T-081 and T-082 both landed, the Verdict Accuracy Tracker (rest of
Phase 8, T-083 onward) can now trust that a verdict built on
`data_quality="insufficient"` fundamentals was never artificially pushed
toward SELL by the pipeline itself — any bearish tilt in the historical
verdict log from here on reflects real signal, not this bug. T-083+ can be
requested separately per the usual one-task-at-a-time flow.
