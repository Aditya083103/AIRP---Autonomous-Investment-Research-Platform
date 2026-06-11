# T-024 — Build News Sentiment Agent

**Phase:** 2 — Research Agents
**Week:** 05
**Branch:** `feat/agent-sentiment`
**Task status:** Ready to merge

---

## Overview

This document covers the complete git workflow for T-024, from branch checkout
to merged PR. T-024 builds the News Sentiment Agent — the third of four
parallel research agents in the AIRP investment committee.

**Agent persona:** Financial journalist with 15 years covering Indian equities.
Reads market news looking for the story behind the story.

**Tools used:**
- `fetch_news` (NewsAPI, last 30 days)
- `semantic_search` (ChromaDB similarity search on `airp_news` collection)

**Output:** `SentimentAnalysis` (score -1 to +1, label, red_flags, headlines,
topics, summary)

---

## 1. Pre-work Checklist

Before starting, confirm main is clean and CI is green:

```bash
git checkout main
git pull origin main
```

Confirm you are at the tip of main:

```bash
git log --oneline -5
```

---

## 2. Create the Feature Branch

```bash
git checkout -b feat/agent-sentiment
```

Confirm:

```bash
git branch
# * feat/agent-sentiment
#   main
```

---

## 3. Files to Create

Place these files exactly at the paths shown:

| File | Path |
|------|------|
| Agent | `backend/agents/sentiment_analyst.py` |
| Tests | `backend/tests/unit/test_sentiment_analyst.py` |
| Docs | `docs/week-05/T-024-build-news-sentiment-agent.md` |

Create the `docs/week-05/` folder if it does not already exist:

```bash
mkdir -p docs/week-05
```

---

## 4. Implementation Notes

### 4.1 Section Comments (Critical — No Unicode)

All section comments in the agent file use plain ASCII `# ---` dividers.
**Do NOT use** `# ─────` or any Unicode box-drawing characters.
They caused repeated `flake8 E501` failures in T-022 and T-023.

Correct:
```python
# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
```

Wrong:
```python
# ─────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────
```

### 4.2 No `from __future__ import annotations`

This import is **absent by design** in the agent file. It breaks Pydantic v2
union type resolution. The test file uses it (safe in test files).

### 4.3 Import Pattern

`settings` must be imported at module level (not inside functions) so tests
can patch it. The agent uses module-level tool imports:

```python
from backend.agents.llm_factory import get_llm
from backend.agents.output_models import SentimentAnalysis
from backend.db.chroma_client import COLLECTION_NEWS, semantic_search
from backend.tools.news import fetch_news
```

### 4.4 Error Convention

- `fetch_news` failure → return `SentimentAnalysis` with `error` set
- `semantic_search` failure → **non-fatal**, log warning, continue
- LLM failure → fallback summary from deterministic data, `error=None`
- Never raises from the node function

### 4.5 Scoring Architecture

The scoring pipeline is split into three layers:

1. **Deterministic** (pure Python, no LLM):
   - `_score_article()` — keyword-weighted per-article score
   - `_aggregate_scores()` — arithmetic mean, clamped to [-1, 1]
   - `_label_from_score()` — band mapping
   - `_detect_red_flags()` — keyword scanner for SEBI, fraud, etc.

2. **LLM synthesis** (narrative only):
   - Top positive/negative headlines selection
   - Dominant topics identification
   - Red flag augmentation
   - 2-3 sentence summary

3. **Merge** (deterministic overrides LLM for scoring):
   - Final `sentiment_score` and `sentiment_label` always come from layer 1
   - Red flags = union of layer 1 and layer 2 (deduplicated)

---

## 5. Run Pre-commit Hooks Locally

From the repo root with `.venv` active:

```bash
black backend/agents/sentiment_analyst.py
isort backend/agents/sentiment_analyst.py
flake8 backend/agents/sentiment_analyst.py

black backend/tests/unit/test_sentiment_analyst.py
isort backend/tests/unit/test_sentiment_analyst.py
flake8 backend/tests/unit/test_sentiment_analyst.py
```

All three must produce **zero output** (no errors, no warnings).

---

## 6. Run the Tests

Set the test environment first (Windows — run as a **separate command**,
not chained with `&&`):

```bash
set ENVIRONMENT=test
```

Then run the tests:

```bash
python -m pytest backend/tests/unit/test_sentiment_analyst.py -v
```

Expected: all tests pass. Target: 100% pass rate on the new file.

Run the full unit test suite to confirm no regressions:

```bash
python -m pytest backend/tests/unit/ -v --tb=short
```

---

## 7. Commit

Stage the three files:

```bash
git add backend/agents/sentiment_analyst.py
git add backend/tests/unit/test_sentiment_analyst.py
git add docs/week-05/T-024-build-news-sentiment-agent.md
```

Commit with the correct format (imperative mood, scope in parentheses):

```bash
git commit -m "feat(agents): add News Sentiment agent with keyword scoring and red flag detection"
```

Verify the commit:

```bash
git log --oneline -3
```

---

## 8. Push the Branch

```bash
git push origin feat/agent-sentiment
```

---

## 9. Open the Pull Request

Go to GitHub → your repo → **Pull requests** → **New pull request**.

- **Base branch:** `main`
- **Compare branch:** `feat/agent-sentiment`
- **Title:** `feat(agents): T-024 — News Sentiment Agent`

Use this PR description:

---

### PR Description

```
## Summary

Implements the News Sentiment Agent (T-024), the third of four parallel
research agents in the AIRP investment committee. The agent fetches the last
30 days of news via the `fetch_news` tool, scores each article using a
keyword-weighted approach, detects red flags deterministically (SEBI notices,
fraud, regulatory actions), and calls the LLM only for narrative synthesis.

## Changes

- `backend/agents/sentiment_analyst.py` — complete News Sentiment Agent
  - `_score_article()` — keyword-weighted per-article sentiment scorer
  - `_aggregate_scores()` — arithmetic mean, clamped to [-1, 1]
  - `_label_from_score()` — score-to-label band mapping
  - `_detect_red_flags()` — deterministic red flag keyword scanner
  - `_build_sentiment_prompt()` — LLM prompt builder
  - `_run_sentiment_analysis_core()` — testable core logic
  - `run_sentiment_analysis()` — LangGraph node entry point
- `backend/tests/unit/test_sentiment_analyst.py` — full unit test suite
  covering all pure functions, core agent, and LangGraph node
- `docs/week-05/T-024-build-news-sentiment-agent.md` — this workflow document

## Testing

All tests pass locally:

```
python -m pytest backend/tests/unit/test_sentiment_analyst.py -v
```

Acceptance criteria verified:
- Sentiment score is directionally correct for positive news (score > 0)
- Sentiment score is directionally correct for negative news (score < 0)
- `red_flags` is populated when SEBI / fraud keywords are present
- Agent never raises — always returns dict with `sentiment` key
- ChromaDB failure is non-fatal (graceful degradation)
- LLM failure produces fallback summary, not an error

## Related Issues

Closes #24
```

---

## 10. CI Gate

After pushing, GitHub Actions CI runs automatically. Confirm both jobs pass:

**Backend CI (`backend-ci`):**
- `mypy backend/` — type checking
- `flake8 backend/` — linting
- `pytest backend/tests/unit/` — unit tests

**Frontend CI (`frontend-ci`):**
- Marked `continue-on-error: true` (Phase 6 task)
- Does not block the `ci-pass` gate

The `ci-pass` required status check must be green before merging.

---

## 11. Merge

Once CI is green:

1. On GitHub, select **Squash and merge**
2. Confirm the squash commit message:
   `feat(agents): T-024 — News Sentiment Agent (#24)`
3. Click **Confirm squash and merge**
4. Delete the branch on GitHub (button appears after merge)

Locally, clean up:

```bash
git checkout main
git pull origin main
git branch -d feat/agent-sentiment
```

---

## 12. Post-Merge Verification

Confirm the merge commit appears on main:

```bash
git log --oneline -5
```

Run the full unit test suite one final time from main to confirm no
regressions:

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/ -v --tb=short
```

---

## 13. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Keyword-based scoring (no NLTK/TextBlob) | Zero new CI dependencies; fully unit-testable; deterministic |
| LLM used only for narrative, not scoring | Score reproducibility; LLM failure does not corrupt output model |
| Red flag detection is deterministic | SEBI notices must not be missed due to LLM hallucination |
| ChromaDB failure is non-fatal | Agent runs on NewsAPI alone if vector store is unavailable |
| `sentiment_score` always from deterministic layer | LLM cannot override the numerical score — only the narrative |
| Fallback summary on LLM failure | `error=None` on LLM failure; graceful degradation per AIRP convention |

---

## 14. Acceptance Criteria Mapping

| Criterion | Test(s) | Status |
|-----------|---------|--------|
| Score directionally correct for positive news | `test_positive_news_gives_positive_score` | Verified |
| Score directionally correct for negative news | `test_negative_news_gives_negative_score` | Verified |
| red_flags populated for SEBI/fraud news | `test_red_flags_detected_for_sebi_news` | Verified |
| No red_flags for clean news | `test_no_red_flags_for_clean_news` | Verified |
| Never raises from node function | `test_never_raises_on_catastrophic_failure` | Verified |
| ChromaDB failure non-fatal | `test_chroma_failure_is_non_fatal` | Verified |
| LLM failure uses fallback | `test_llm_failure_uses_fallback_summary` | Verified |
| SentimentAnalysis model validates | `test_model_serialisable` | Verified |

---

*T-024 complete. Next: T-025 — Build Macro Economist Agent.*