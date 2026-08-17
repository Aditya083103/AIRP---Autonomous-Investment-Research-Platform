# AIRP — Verdict Accuracy Evaluation Methodology

> **Canonical reference for how AIRP scores its own BUY / HOLD / SELL verdicts against
> real market outcomes.** Covers Phase 8 (T-087–T-092): the `verdict_outcomes` schema,
> the evaluation-horizon mapping, the dead-zone directional scoring rule, and the public
> API + dashboard that expose the results. Update this file whenever the horizon mapping,
> the dead-zone percentage, or the aggregation logic changes.
>
> **Looking for the LangSmith agent-quality eval suite instead** (Fundamental Analyst
> accuracy, Sentiment direction, Debate quality, latency benchmarks — Phase 11,
> T-067–T-072)? That's a separate, complementary system — see
> [`docs/AGENT_EVALUATION.md`](AGENT_EVALUATION.md).

---

## Table of Contents

1. [Why this exists](#1-why-this-exists)
2. [The pipeline, end to end](#2-the-pipeline-end-to-end)
3. [Evaluation-horizon mapping](#3-evaluation-horizon-mapping)
4. [The dead-zone directional scoring rule](#4-the-dead-zone-directional-scoring-rule)
5. [Worked examples](#5-worked-examples)
6. [Aggregation: summary and history](#6-aggregation-summary-and-history)
7. [The public API and dashboard](#7-the-public-api-and-dashboard)
8. [Design rationale (FAQ)](#8-design-rationale-faq)
9. [Known limitations](#9-known-limitations)

---

## 1. Why this exists

Every AI investment-research demo can show you a plausible-sounding memo. Very few show
you whether their past verdicts were actually *right*. AIRP's Verdict Accuracy Tracker
(Phase 8) closes that loop: every BUY/HOLD/SELL verdict the Portfolio Manager agent issues
is recorded at the moment it's made, automatically re-checked against the real market once
enough time has passed to judge it fairly, and the aggregate results are published on a
public dashboard — no login required, nothing hidden.

This document is the methodology write-up: given a verdict and a later price, exactly how
does AIRP decide "was this call right?", and exactly how long does it wait before checking?

## 2. The pipeline, end to end

| Stage | Task | What happens |
| --- | --- | --- |
| **Record** | T-088 | The moment a pipeline run reaches `status == "completed"`, `record_pending_evaluations()` writes one `verdict_outcomes` row: ticker, verdict, conviction score, the price the Technical Analyst saw at verdict time, and an `evaluation_horizon_days` value (see [§3](#3-evaluation-horizon-mapping)). The four evaluation-time columns (`price_at_evaluation`, `price_change_pct`, `directional_correct`, `evaluated_at`) are left `NULL` — the row starts life *pending*. |
| **Wait** | — | Nothing happens until `verdict_date + evaluation_horizon_days` has passed. A verdict is never judged early. |
| **Evaluate** | T-089 | A daily scheduled job (`POST /api/v1/accuracy/run`, T-090) calls `run_due_evaluations()`, which finds every pending row whose horizon has elapsed, fetches the ticker's current price, computes the percent change from `price_at_verdict`, and applies the dead-zone rule (see [§4](#4-the-dead-zone-directional-scoring-rule)) to decide `directional_correct`. |
| **Aggregate** | T-091 | `GET /api/v1/accuracy/summary` and `GET /api/v1/accuracy/history` turn the scored rows into an overall accuracy percentage, a breakdown by verdict type, and a breakdown by conviction-score bucket. |
| **Publish** | T-092 | `AccuracyPage.tsx` renders three charts and a stats row from those two endpoints at the public `/accuracy` route — no account needed. |

Every stage is designed to **never raise** — a temporarily unreachable price feed, a
malformed state dict, or a duplicate insert is logged and skipped, not allowed to fail
the analysis or the batch job it's part of. See
`backend/services/accuracy_tracker.py`'s own module docstring for the full "never
raises" contract each function follows.

## 3. Evaluation-horizon mapping

`derive_evaluation_horizon_days(verdict, time_horizon)` collapses the Portfolio
Manager's four possible `time_horizon` labels down to just **two** concrete evaluation
horizons:

| Constant | Value | Applies to |
| --- | --- | --- |
| `DEFAULT_EVALUATION_HORIZON_DAYS` | **90 days** | Every verdict/time_horizon combination *except* the one row below |
| `HIGH_CONFIDENCE_EVALUATION_HORIZON_DAYS` | **365 days** | Only a **BUY** verdict whose `time_horizon` text contains "high margin of safety" |

The Portfolio Manager's `_determine_time_horizon()` can emit exactly four free-text
labels, depending on the verdict and what's driving it:

| `time_horizon` text produced | When | Evaluation horizon used |
| --- | --- | --- |
| `"quarterly review (3 months)"` | Every **HOLD** verdict | 90 days (default) |
| `"3-6 months (technically driven, reassess on momentum shift)"` | Technical signal strength ≥ 8 | 90 days (default) |
| `"3-5 years (high margin of safety supports a long hold)"` | **BUY** verdict with a high DCF margin of safety | **365 days** |
| `"12 months"` | Every other BUY/SELL case | 90 days (default) |

**The important nuance:** the accuracy tracker does not trust the memo's stated holding
period at face value. A BUY verdict labelled `"12 months"` in the Investment Memo is
still checked back at **90 days**, not 12 months — only the one specific "high margin of
safety" branch earns the long 365-day horizon. This keeps the tracker answering one
narrow, consistent question — *"was this verdict directionally right about a quarter
later?"* — rather than trying to hold every verdict to whatever holding period its own
prose happened to mention.

A row becomes **due** once `verdict_date + evaluation_horizon_days <= now` (an inclusive
comparison — a row due at exactly midnight on day 90 is picked up by that day's run, not
skipped until day 91).

## 4. The dead-zone directional scoring rule

`score_directional_correctness(verdict, price_change_pct)` applies a **±5% dead zone**
(`DEAD_ZONE_PCT = 5.0`) that absorbs ordinary price noise, so a verdict is never
penalised for a move too small to represent a real directional outcome. The rule is
**asymmetric per verdict type** — each verdict only fails when the price moves *against*
what it predicted by more than the dead zone:

| Verdict | Scored **wrong** when… | Scored **correct** when… |
| --- | --- | --- |
| **BUY** | Price fell by 5% or more (`price_change_pct <= -5.0`) | Anything else — flat, a small dip, or any rise |
| **SELL** | Price rose by 5% or more (`price_change_pct >= 5.0`) | Anything else — flat, a small rise, or any fall |
| **HOLD** | Price moved 5% or more in *either* direction | The move stayed strictly inside (-5%, +5%) |

**Boundary semantics:** the dead zone is the **open interval** `(-5.0%, +5.0%)`. A move
of *exactly* ±5.0% counts as having **left** the dead zone — a HOLD at exactly +5.0% is
wrong, a BUY at exactly -5.0% is wrong. 5% is meant to be the point at which a move stops
being noise, not one step short of it.

Any verdict string outside `BUY` / `HOLD` / `SELL` is defensively scored with the HOLD
rule — the strictest of the three — though this should never occur in practice since
`VerdictOutcome.verdict` is DB-enum-constrained.

## 5. Worked examples

### 5.1 Horizon mapping

| Ticker (illustrative) | Verdict | Why | `time_horizon` text | Evaluation horizon |
| --- | --- | --- | --- | --- |
| TCS.NS | HOLD | Conviction insufficient to lean either way | `"quarterly review (3 months)"` | 90 days |
| INFY.NS | BUY | Strong technical momentum (signal strength 9) | `"3-6 months (technically driven, reassess on momentum shift)"` | 90 days |
| HDFCBANK.NS | BUY | DCF shows a high margin of safety | `"3-5 years (high margin of safety supports a long hold)"` | **365 days** |
| WIPRO.NS | SELL | Weak fundamentals, no special flags | `"12 months"` | 90 days |

Note the second row: a technically-driven BUY still gets the default 90-day horizon,
*not* the long one — only the margin-of-safety branch on the third row does.

### 5.2 Dead-zone scoring — BUY verdict, `price_at_verdict = ₹3,000`

| Price 90 days later | `price_change_pct` | Verdict outcome | Why |
| --- | --- | --- | --- |
| ₹3,300 | +10.00% | ✅ Correct | Any rise is correct for a BUY |
| ₹3,000 | 0.00% | ✅ Correct | Flat is correct for a BUY |
| ₹2,900 | -3.33% | ✅ Correct | Small dip stays inside the dead zone |
| ₹2,850 | **-5.00%** | ❌ Wrong | Exactly at the boundary — counted as having left the dead zone |
| ₹2,700 | -10.00% | ❌ Wrong | Fell hard, well past the dead zone |

### 5.3 Dead-zone scoring — SELL verdict, `price_at_verdict = ₹1,500`

| Price 90 days later | `price_change_pct` | Verdict outcome | Why |
| --- | --- | --- | --- |
| ₹1,350 | -10.00% | ✅ Correct | Any fall is correct for a SELL |
| ₹1,573.50 | +4.90% | ✅ Correct | Just inside the dead zone |
| ₹1,575 | **+5.00%** | ❌ Wrong | Exactly at the boundary |
| ₹1,650 | +10.00% | ❌ Wrong | Rose hard, against the call |

### 5.4 Dead-zone scoring — HOLD verdict, `price_at_verdict = ₹800`

| Price 90 days later | `price_change_pct` | Verdict outcome | Why |
| --- | --- | --- | --- |
| ₹820 | +2.50% | ✅ Correct | Inside the dead zone |
| ₹760 | -5.00% | ❌ Wrong | Left the dead zone on the downside |
| ₹840 | +5.00% | ❌ Wrong | Left the dead zone on the upside |
| ₹795 | -0.63% | ✅ Correct | Barely moved — exactly what a HOLD predicts |

## 6. Aggregation: summary and history

`get_accuracy_summary()` computes three things from every scored (`evaluated_at IS NOT
NULL`) row in `verdict_outcomes`:

- **Overall accuracy** — `correct_count / evaluated_count * 100`, rounded to 2 decimal
  places. `null` (never a fabricated `0%`) when nothing has been scored yet.
- **By verdict type** — one row each for BUY, HOLD, and SELL, always present even when a
  verdict type has zero scored rows so far.
- **By conviction bucket** — the Portfolio Manager's 1–10 conviction score split into
  three fixed buckets: **Low (1–3)**, **Medium (4–6)**, **High (7–10)**. Always exactly
  three entries, same "never a fabricated 0%" rule for an empty bucket.

`get_accuracy_history()` returns every `verdict_outcomes` row — evaluated or still
pending — paginated, newest verdict first. This is the row-level data the frontend's
rolling-accuracy trend line and conviction-vs-outcome scatter chart are built from (see
[§7](#7-the-public-api-and-dashboard)).

## 7. The public API and dashboard

Both endpoints are **public — no authentication required.** `verdict_outcomes` is a
platform-wide statistic, not scoped to any one user, and the whole point of Phase 8 is
transparency: anyone can check AIRP's track record without an account.

| Endpoint | Returns |
| --- | --- |
| `GET /api/v1/accuracy/summary` | Overall accuracy % + the two breakdowns above |
| `GET /api/v1/accuracy/history?limit=&offset=` | Paginated row-level outcomes, newest first |

The `/accuracy` route (T-092) renders three charts entirely from this data:

1. **Rolling accuracy trend** — a **10-verdict rolling window** (not cumulative
   accuracy-to-date) over evaluated verdicts, so the line stays responsive to recent
   performance rather than slowly converging and going flat after a few hundred scored
   verdicts.
2. **Accuracy by verdict type** — one bar per BUY/HOLD/SELL from the summary's
   `by_verdict` breakdown.
3. **Conviction vs. outcome** — one point per evaluated verdict, conviction score against
   the actual price-change percentage, coloured by whether the call was directionally
   correct — a finer-grained picture than the bucketed conviction rollup can show.

The README's accuracy badge (top of this repo) is a live `shields.io` dynamic badge
reading `overall_accuracy_pct` directly from `GET /api/v1/accuracy/summary` — it reflects
whatever the deployed API currently reports, with no separate badge-generation step to
keep in sync.

## 8. Design rationale (FAQ)

**Why a dead zone at all, instead of scoring any rise/fall as right/wrong?**
Daily stock price moves of a few percent are routine noise, not a verdict succeeding or
failing. Without a dead zone, a HOLD verdict would almost never be scored correct (the
price essentially never sits at exactly the verdict-time value 90 days later), and a BUY
would be marked wrong for an ordinary down day that has nothing to do with whether the
investment thesis was sound.

**Why is the dead zone asymmetric per verdict, rather than one universal ±5% "was it
close" rule?**
A BUY and a SELL each only make a claim about *one* direction. A BUY says "this will not
fall hard" — it does not also claim "and it definitely will not accidentally drop 2%
first." Scoring a BUY wrong for a rise, or a SELL wrong for a fall, would penalise a
verdict for happening to be *right*.

**Why does the horizon mapping collapse four time-horizon labels into just two
durations?**
Answering "was this verdict right, checked against a consistent, predictable schedule"
is simpler and more auditable than trying to hold every verdict accountable to whatever
holding-period phrase its own memo prose happened to use. Two buckets (90 vs. 365 days)
keeps the tracker's own logic — and this document — easy to state precisely.

**Why does only the "high margin of safety" BUY case get the long 365-day horizon?**
It is the one case `_determine_time_horizon()` itself treats as a genuine multi-year
hold. Every other case, including a technically-driven BUY with strong near-term
momentum, is fundamentally a shorter-term call and is checked back sooner.

**Why is `null` used instead of `0%` when nothing has been evaluated yet?**
A verdict type or conviction bucket with zero scored rows has an *unknown* accuracy, not
a demonstrated 0% (all-wrong) track record. Collapsing the two would make a bucket that
simply hasn't been checked yet look identical to one that has been checked and found
completely wrong.

## 9. Known limitations

- **Single-price evaluation.** Accuracy is judged against the closing price on exactly
  one day (`verdict_date + evaluation_horizon_days`), not against the best or worst price
  reached at any point during the holding period. A verdict that was briefly very right
  or very wrong along the way, but happened to land back near the dead-zone boundary on
  evaluation day, is scored by that one snapshot.
- **No survivorship adjustment.** A ticker that is delisted, merged, or otherwise
  unreachable via yFinance before its evaluation date is simply skipped by
  `run_due_evaluations()` (logged, `evaluated_at` stays `NULL`) rather than counted as
  incorrect or excluded from the denominator in some other way.
- **Fixed thresholds.** `DEAD_ZONE_PCT` (5.0) and the two horizon buckets (90 / 365 days)
  are constants, not adjusted per sector volatility, market regime, or holding-period
  label. A highly volatile small-cap and a stable large-cap are held to the same ±5%
  bar.

---

_Phase 8 — Verdict Accuracy Tracker. Implemented across T-087 (schema) → T-088 (record)
→ T-089 (evaluate) → T-090 (scheduled run) → T-091 (public API) → T-092 (dashboard) →
T-093 (this document + README badge)._