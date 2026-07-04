# T-023 — Build Technical Analyst Agent

**Phase:** 2 — Research Agents
**Week:** 4
**Branch:** `feat/agent-technical`
**Status:** Complete

---

## 1. Overview

Implements the **Technical Analyst** — the second of the eight AIRP investment
committee agents. The agent fetches 1 year of daily OHLCV price data via
`fetch_stock_price` and computes all technical indicators deterministically
in pure Python (no pandas, no TA-lib) before calling the LLM for a 2–3
sentence narrative summary.

---

## 2. Files Delivered

| File                                                  | Description            |
| ----------------------------------------------------- | ---------------------- |
| `backend/agents/technical_analyst.py`                 | Agent implementation   |
| `backend/tests/unit/test_technical_analyst.py`        | Unit tests (~90 tests) |
| `docs/week-04/T-023-build-technical-analyst-agent.md` | This document          |

---

## 3. Agent Architecture

```
run_technical_analysis(state)              ← LangGraph node
    │
    ├── fetch_stock_price.invoke(ticker, "1y")   ← 1-year OHLCV
    │
    ├── compute_sma(closes, 50)            ← Pure: SMA-50
    ├── compute_sma(closes, 200)           ← Pure: SMA-200
    ├── compute_rsi(closes, 14)            ← Pure: RSI-14 (Wilder's)
    ├── compute_momentum(closes, 21/63/126/252)  ← Pure: 1m/3m/6m/1y
    ├── _compute_volume_trend(ohlcv)       ← Pure: volume classification
    ├── _extract_key_levels(ohlcv)         ← Pure: support/resistance
    ├── _determine_signal(...)             ← Pure: BUY/HOLD/SELL + strength
    │
    ├── get_llm().invoke(messages)         ← LLM: summary only
    │
    └── TechnicalAnalysis(...)             ← Validated Pydantic output
            │
            └── {"technical": result.model_dump()} → InvestmentState
```

---

## 4. Technical Indicator Formulas

### SMA (Simple Moving Average)

```
SMA(n) = (close[t-n+1] + ... + close[t]) / n
```

- SMA-50: last 50 daily closes
- SMA-200: last 200 daily closes
- Returns `None` when insufficient data (< n closes available)

### RSI-14 (Wilder's Exponential Smoothing)

Standard formula matching TradingView / Bloomberg:

```
Step 1: delta[i] = close[i] - close[i-1]
Step 2: gain[i]  = max(delta[i], 0)
        loss[i]  = abs(min(delta[i], 0))
Step 3: seed avg_gain = mean(gain[0..13])
              avg_loss = mean(loss[0..13])
Step 4: for each subsequent i:
            avg_gain = (avg_gain * 13 + gain[i]) / 14
            avg_loss = (avg_loss * 13 + loss[i]) / 14
Step 5: RS  = avg_gain / avg_loss
        RSI = 100 - (100 / (1 + RS))
```

**Manual verification** (included in test docstring):

```
closes = [10,12,11,13,14,12,13,15,14,16,15,17,16,18,19]
gains  sum = 15.0,  avg_gain = 15/14 ≈ 1.0714
losses sum = 6.0,   avg_loss =  6/14 ≈ 0.4286
RS = 2.5,  RSI = 100 - 100/3.5 ≈ 71.43
```

### Momentum

```
momentum(n) = (close[-1] - close[-(n+1)]) / close[-(n+1)] × 100
```

Computed for n = 21 (1m), 63 (3m), 126 (6m), 252 (1y) trading days.

---

## 5. Signal Determination

Five binary checks, each contributes 1 bullish or 1 bearish point:

| Check           | Bullish                 | Bearish                               |
| --------------- | ----------------------- | ------------------------------------- |
| Price vs MA-50  | price > MA-50           | price < MA-50                         |
| Price vs MA-200 | price > MA-200          | price < MA-200                        |
| MA cross        | MA-50 > MA-200 (golden) | MA-50 < MA-200 (death)                |
| RSI             | 30 ≤ RSI ≤ 70           | RSI < 30 **or** RSI > 75 (exhaustion) |
| 3m momentum     | > 0%                    | < 0%                                  |

**Decision:**

- `BUY` if bullish_count ≥ 4
- `SELL` if bearish_count ≥ 4
- `HOLD` otherwise

**Strength (1–10):**

- BUY/SELL: `min(10, 5 + count)` → range 6–10
- HOLD: `max(1, min(7, 3 + |bull - bear|))` → range 3–7

Note: RSI 70–75 is intentionally **neutral** (no point either way) — this
range represents a mildly overbought condition, not exhaustion.

---

## 6. Acceptance Criteria Verification

| Criterion                        | Status | Test                                                 |
| -------------------------------- | ------ | ---------------------------------------------------- |
| RSI computed correctly vs manual | ✅     | `TestComputeRSI.test_rsi_known_result` — RSI ≈ 71.43 |
| SMA-50 computed correctly        | ✅     | `TestComputeSMA.test_sma_50_on_260_closes` — 3234.5  |
| SMA-200 computed correctly       | ✅     | `TestComputeSMA.test_sma_200_on_260_closes` — 3159.5 |
| TCS output validated             | ✅     | `TestRunTechnicalAnalysisNode.test_tcs_state`        |
| Infosys output validated         | ✅     | `TestRunTechnicalAnalysisNode.test_infy_state`       |
| Reliance output validated        | ✅     | `TestRunTechnicalAnalysisNode.test_reliance_state`   |
| Signal covers all 3 outcomes     | ✅     | `TestDetermineSignal`                                |
| Never raises                     | ✅     | `test_never_raises_on_catastrophic_failure`          |
| LangSmith trace visible          | ✅     | Auto via LangChain instrumentation                   |

---

## 7. Git Flow

### 7.1 Branch checkout

```bash
git checkout main
git pull origin main
git checkout -b feat/agent-technical
```

### 7.2 Place files

```
backend/agents/technical_analyst.py
backend/tests/unit/test_technical_analyst.py
docs/week-04/T-023-build-technical-analyst-agent.md
```

### 7.3 Pre-commit checks

```bash
black backend/agents/technical_analyst.py \
      backend/tests/unit/test_technical_analyst.py
isort backend/agents/technical_analyst.py \
      backend/tests/unit/test_technical_analyst.py
flake8 backend/agents/technical_analyst.py \
       backend/tests/unit/test_technical_analyst.py
mypy backend/agents/technical_analyst.py
```

### 7.4 Run tests

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_technical_analyst.py -v
```

Expected: all ~90 tests pass. Then full suite:

```bash
python -m pytest -m "not integration" --tb=short -q
```

### 7.5 Commit

```bash
git add backend/agents/technical_analyst.py
git add backend/tests/unit/test_technical_analyst.py
git add docs/week-04/T-023-build-technical-analyst-agent.md

git commit -m "feat(agents): build Technical Analyst agent (T-023)

- compute_rsi: Wilder's 14-period RSI matching TradingView/Bloomberg
- compute_sma: SMA-50 and SMA-200 from closing prices
- compute_momentum: 1m/3m/6m/1y price return (pure Python)
- _determine_signal: BUY/HOLD/SELL from 5 binary checks
  (price vs MA50/200, golden cross, RSI band, 3m momentum)
- _extract_key_levels: swing high/low over 60-day window
- _compute_volume_trend: 30-day vs prior-30-day volume comparison
- _build_technical_prompt: structured prompt with pre-computed indicators
- _run_technical_analysis_core: fetch → compute → LLM narrative
- run_technical_analysis: LangGraph node (reads job_id/company_name/ticker,
  writes {'technical': result.model_dump()})
- Error convention: never raises; TechnicalAnalysis.error set on failure
- ~90 unit tests: RSI/SMA verified vs manual calculation, all signal
  branches, TCS/INFY/RELIANCE state shapes, error paths

Closes #23"
```

### 7.6 Push and open PR

```bash
git push -u origin feat/agent-technical
```

---

## 8. Pull Request

### Title

```
feat(agents): build Technical Analyst agent (T-023)
```

### Description

````markdown
## Summary

Implements the Technical Analyst — the second AIRP investment committee agent.
The agent computes all technical indicators (SMA-50/200, RSI-14, momentum,
volume trend, support/resistance) deterministically in pure Python, determines
the BUY/HOLD/SELL signal from 5 binary checks, then calls the LLM only for
a 2–3 sentence narrative summary. RSI uses Wilder's exponential smoothing,
verified against manual calculation.

## Changes

- `backend/agents/technical_analyst.py`
  - `compute_sma(closes, window)` — pure SMA, unit-testable
  - `compute_rsi(closes, period)` — Wilder's RSI, unit-testable
  - `compute_momentum(closes, lookback)` — % price return, unit-testable
  - `_determine_signal(price, ma50, ma200, rsi, momentum_3m)` — 5-check
    deterministic BUY/HOLD/SELL with strength 1–10
  - `_extract_key_levels(ohlcv)` — swing high/low support/resistance
  - `_compute_volume_trend(ohlcv)` — 30d vs prior-30d volume comparison
  - `_build_technical_prompt(...)` — structured LLM prompt
  - `_run_technical_analysis_core(...)` — testable core
  - `run_technical_analysis(state)` — LangGraph node

- `backend/tests/unit/test_technical_analyst.py` — ~90 unit tests:
  - RSI-14 verified vs manual Wilder's calculation (expected 71.43)
  - SMA-50 (3234.5) and SMA-200 (3159.5) verified on known series
  - Signal determination across BUY/HOLD/SELL and all edge cases
  - TCS / Infosys / Reliance state shape validation
  - Error paths: tool failure, LLM failure, malformed JSON, empty ticker

## Testing

```bash
set ENVIRONMENT=test
python -m pytest backend/tests/unit/test_technical_analyst.py -v
# ~90 passed
```
````

## LangSmith Trace

Automatic via LangChain instrumentation. No additional code required.

## Related Issues

Closes #23

````

---

## 9. Usage in LangGraph (Phase 3)

```python
from backend.agents.technical_analyst import run_technical_analysis

builder.add_node("technical_analyst", run_technical_analysis)

# Reads from InvestmentState:
#   state["job_id"]        → analysis_id
#   state["company_name"]  → company name
#   state["ticker"]        → Yahoo Finance ticker

# Writes to InvestmentState:
#   state["technical"]     → dict from TechnicalAnalysis.model_dump()

# Error check:
#   if state["technical"]["error"] is not None:
#       # degrade gracefully
````
