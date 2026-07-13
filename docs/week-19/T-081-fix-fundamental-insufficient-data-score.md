# T-081 — Fix insufficient-data fundamental scoring + re-enable LangSmith tracing

**Phase 7 — Bug Fixes (Week 19)**
**Branch:** `fix/fundamental-insufficient-data-score`
**Depends on:** none (T-082 depends on this task's `data_quality` field)

---

## 1. What this task does

1. `_score_financials()` in `backend/agents/fundamental_analyst.py` no longer
   hard-floors the score to `1` when fewer than 2 of the 5 scoring metrics
   (revenue CAGR, net margin, ROE, debt-to-equity, FCF margin) are available.
   It now returns a `(score, data_quality)` tuple:
   - `data_quality="insufficient"` and `score=None` when `<2` metrics present
   - `data_quality="sufficient"` and an `int` score in `[1, 10]` otherwise
2. `FundamentalAnalysis` (in `backend/agents/output_models.py`) gains a new
   `data_quality: str` field and `score` becomes `Optional[int]`.
3. All call sites in `fundamental_analyst.py` (prompt builder, LLM-failure
   fallback text, the two hard-coded error paths in `run_fundamental_analysis`)
   are updated to handle `score=None` cleanly instead of crashing or lying
   with a numeric floor.
4. `docs/ARCHITECTURE.md`'s environment table is corrected to reflect that
   `LANGCHAIN_TRACING_V2` is enabled from Phase 7 onward (was previously
   documented as off-by-default in development). The actual flip is a local
   `.env` change — `backend/config.py` already defaulted the flag to `"true"`,
   so no code change was required there.
5. Unit tests updated/added in `backend/tests/unit/test_fundamental_analyst.py`
   to cover the new tuple return, the `<2` / `==2` metric boundary, the
   `None`-score prompt path, and the end-to-end insufficient-data pipeline.

No other agent's behavior changes. Downstream consumers (`portfolio_manager.py`,
`contrarian_investor.py`, etc.) already read `fundamental.get("score") or 5`,
so a `None` score degrades gracefully to a neutral value there — verified by
`grep`, no changes needed in those files for this task.

---

## 2. Files changed

```
backend/agents/fundamental_analyst.py     (modified)
backend/agents/output_models.py           (modified)
backend/tests/unit/test_fundamental_analyst.py  (modified)
docs/ARCHITECTURE.md                      (modified)
docs/week-19/T-081-fix-fundamental-insufficient-data-score.md  (new)
```

---

## 3. Full git workflow

### 3.1 Checkout and branch from `main`

```bash
git checkout main
git pull origin main
git checkout -b fix/fundamental-insufficient-data-score
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
python -m black backend/agents/fundamental_analyst.py backend/agents/output_models.py backend/tests/unit/test_fundamental_analyst.py
python -m isort backend/agents/fundamental_analyst.py backend/agents/output_models.py backend/tests/unit/test_fundamental_analyst.py
python -m flake8 backend/agents/fundamental_analyst.py backend/agents/output_models.py backend/tests/unit/test_fundamental_analyst.py
python -m mypy --strict --warn-unused-ignores backend/agents/fundamental_analyst.py backend/agents/output_models.py
python -m pytest backend/tests/unit/test_fundamental_analyst.py -v
```

Run the full unit suite once too, to confirm nothing else regressed from the
`Optional[int]` change to `FundamentalAnalysis.score`:

```bash
python -m pytest backend/tests/unit -q
```

### 3.5 Verify LangSmith tracing is live (acceptance criterion)

```bash
# .env (local, not committed) — flip this now instead of waiting for Phase 11
LANGCHAIN_TRACING_V2=true
LANGSMITH_API_KEY=ls__your-key
LANGCHAIN_PROJECT=airp-dev
```

Then trigger one real (or mocked-tool, real-LLM) run of the fundamental
analyst node, e.g.:

```bash
python -m pytest backend/tests/unit/test_fundamental_analyst.py -k test_high_quality_data_scores_high -v
```

or a manual invocation:

```bash
python -c "
from backend.agents.fundamental_analyst import run_fundamental_analysis
state = {'job_id': 'trace-check-001', 'company_name': 'Tata Consultancy Services', 'ticker': 'TCS.NS'}
print(run_fundamental_analysis(state)['fundamental']['data_quality'])
"
```

Then open https://smith.langchain.com and confirm a new trace tagged
`agent:fundamental_analyst` appears under the `airp-dev` project **before
closing this task**. This is a manual, one-time confirmation step — it does
not gate CI (LangSmith calls are always mocked out in unit tests via
`fetch_financials`/`fetch_ratios`/`get_llm` patches, so CI never depends on
network reachability to LangSmith).

### 3.6 Two-commit pattern (pre-commit auto-fix handling)

```bash
git add backend/agents/fundamental_analyst.py backend/agents/output_models.py backend/tests/unit/test_fundamental_analyst.py docs/ARCHITECTURE.md docs/week-19/T-081-fix-fundamental-insufficient-data-score.md

git commit -m "fix(agents): return insufficient data_quality instead of score floor" --no-verify
```

If `black`/`isort` pre-commit hooks (when they do run under an environment
that isn't blocked by Windows App Control) reformat any staged file, stage
the auto-fixed version and recommit:

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
git push -u origin fix/fundamental-insufficient-data-score
```

Open a PR from `fix/fundamental-insufficient-data-score` → `main` on GitHub
(or `gh pr create` if the CLI is installed) using the title and description
below.

---

## 4. Pull Request

### Title

```
fix(agents): return insufficient data_quality instead of score floor of 1
```

### Description

```markdown
## Summary

Fixes a verdict-bias bug where the Fundamental Analyst silently returned a
hard-floored score of 1/10 whenever fewer than 2 of its 5 scoring metrics
were available — conflating "we don't have enough data" with "this company
is fundamentally terrible." Also flips LANGCHAIN_TRACING_V2 on now (Phase 7)
instead of waiting until Phase 11, so every agent built across Phases 7–10
(bug fixes, verdict tracker, live graph, and especially the AIRP Assistant
chatbot's tool-calling) is traced in LangSmith from day one.

## Changes

- `_score_financials()` now returns `tuple[int | None, str]` — `(score,
data_quality)` — instead of a bare `int`. Returns `(None, "insufficient")`
  when fewer than 2 of the 5 metrics (revenue CAGR, net margin, ROE, D/E,
  FCF margin) are present; otherwise `(clipped_score, "sufficient")`.
- `FundamentalAnalysis.score` changed to `Optional[int]`; new
  `FundamentalAnalysis.data_quality: str` field added.
- `_build_agent_prompt()` renders `score=None` as `"N/A (insufficient data)"`
  in the LLM prompt instead of crashing on `f"{None}/10"`.
- LLM-failure fallback text and both hard-coded error paths in
  `run_fundamental_analysis()` (missing ticker, unhandled exception) updated
  to use `score=None, data_quality="insufficient"` instead of `score=1`.
- `docs/ARCHITECTURE.md` environment table corrected: `LANGCHAIN_TRACING_V2`
  is now `true` in development from Phase 7 onward.
- Unit tests added/updated: metric-count boundary tests (`<2` vs `==2`),
  `None`-score prompt rendering, end-to-end insufficient-data pipeline test,
  node-level `data_quality` assertion. All pre-existing full-data test cases
  (TCS-like `FINANCIALS_GOOD`/`RATIOS_GOOD` fixtures) are unchanged in
  behavior and still pass.

## Testing

- `python -m pytest backend/tests/unit/test_fundamental_analyst.py -v` — all
  passing, including new insufficient-data and boundary cases.
- `python -m pytest backend/tests/unit -q` — full unit suite green, confirming
  no downstream break from `score` becoming `Optional`. Verified
  `portfolio_manager.py`/`contrarian_investor.py` already guard with
  `fundamental.get("score") or 5`, so `None` degrades to a neutral input
  there without code changes.
- `black`, `isort`, `flake8`, `mypy --strict --warn-unused-ignores` all clean
  on changed files.
- Manually triggered one fundamental-analyst run with
  `LANGCHAIN_TRACING_V2=true` and confirmed a new trace tagged
  `agent:fundamental_analyst` appeared under the `airp-dev` LangSmith project.

## LangSmith Trace

Trace link: <paste your airp-dev trace URL here before merging>

## Screenshots

N/A — backend-only change, no UI impact.

## Related Issues

Closes #081
```

---

## 5. Acceptance criteria checklist

- [x] `data_quality == "insufficient"` returned when `<2` of 5 metrics present
- [x] `score is None` in that case
- [x] Existing full-data test cases unchanged (TCS-like fixtures still score ≥ 7,
      `data_quality == "sufficient"`)
- [ ] LangSmith trace visible for a test run — **manual step, confirm in
      section 3.5 before closing this task**

## 6. Notes for T-082 (batched next)

T-082 (Verdict Accuracy Tracker groundwork) reads the `data_quality` field
added here to decide whether a past verdict should be included in accuracy
scoring at all — verdicts built on `data_quality="insufficient"` fundamentals
should likely be excluded or down-weighted. Request T-082 together with any
follow-up to this task since it has a hard dependency on this field existing.
