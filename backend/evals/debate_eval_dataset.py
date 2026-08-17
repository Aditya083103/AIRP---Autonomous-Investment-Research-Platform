# backend/evals/debate_eval_dataset.py
"""
AIRP -- Debate Quality LangSmith Eval Dataset (T-070)

Ground-truth dataset for the debate-quality eval designed in
docs/EVAL_FRAMEWORK_DESIGN.md §3.3: 5 synthetic post-debate
``InvestmentState`` snapshots -- each with a ``ContrarianReport``-shaped
dict, a ``debate_rounds[]`` transcript matching the real
``backend.graph.state.DebateRound`` shape, and an
``InvestmentDecision``-shaped dict -- spanning 5 different companies and
verdicts (BUY / SELL / HOLD) so the eval isn't just proving the happy
path for one outcome.

Why synthetic snapshots, not a real graph run
-----------------------------------------------
EVAL_FRAMEWORK_DESIGN.md §3.3 proposed reusing
``backend/tests/integration/test_graph_integration.py``-style fixtures.
That file's own mock helpers (``_mock_contrarian_success``, ``_run_graph``,
etc.) are test-module-local (leading underscore, not part of any public
API) and tightly coupled to that file's own mocking of all 8 agent
functions -- importing them here would create a fragile cross-test-file
dependency for no real benefit. Instead, this dataset hand-authors
snapshots that are schema-faithful to the real
``ContrarianReport`` / ``DebateRound`` / ``InvestmentDecision`` shapes
(field-for-field, verified in
backend/tests/unit/test_debate_evaluators.py's ``TestDatasetShape``),
which keeps this eval self-contained and decoupled from the integration
test suite's internal test machinery -- the same reasoning
backend/evals/fundamental_eval_dataset.py and
backend/evals/sentiment_eval_dataset.py already used for their own
synthetic-but-schema-faithful data.

Every one of the 5 snapshots is constructed to PASS every rubric check --
this dataset is the positive proof for "Contrarian always disagrees" /
"debate rounds non-repetitive" / "Portfolio Manager references debate
content" across 5 different runs, not a mix of pass/fail cases. The
grading logic's ability to CATCH a violation is proven separately, with
synthetic malformed fixtures, in
backend/tests/unit/test_debate_evaluators.py's
``TestGradeDebateSnapshot`` class -- mirroring how T-068's insufficient-
data example and T-069's spurious-red-flag test kept "does it grade
correctly" and "is the real system reliably compliant" as separate
concerns.

Public interface
-----------------
    DebateSnapshotExample  -- TypedDict: one full post-debate snapshot
    DEBATE_EVAL_DATASET    -- tuple[DebateSnapshotExample, ...] -- all 5

Usage
-----
    from backend.evals.debate_eval_dataset import DEBATE_EVAL_DATASET

    for example in DEBATE_EVAL_DATASET:
        ...  # grade example["contrarian"] / ["debate_rounds"] / ["decision"]
"""

from typing import Any, TypedDict


class DebateSnapshotExample(TypedDict):
    """One full post-debate InvestmentState snapshot."""

    name: str
    contrarian: dict[str, Any]
    debate_rounds: tuple[dict[str, Any], ...]
    decision: dict[str, Any]
    rationale: str


# ---------------------------------------------------------------------------
# 5 synthetic post-debate snapshots across 5 companies / 3 verdict types
# ---------------------------------------------------------------------------

DEBATE_EVAL_DATASET: tuple[DebateSnapshotExample, ...] = (
    {
        "name": "tcs_quality_compounder_challenged",
        "contrarian": {
            "agent_name": "contrarian_investor",
            "counter_arguments": [
                "The Fundamental Analyst's high score leans heavily on "
                "trailing revenue CAGR, but free cash flow conversion has "
                "quietly declined for three consecutive years -- a trend "
                "the headline score doesn't surface.",
                "Valuation at nearly 28x earnings already prices in "
                "several more years of double-digit growth; any "
                "deceleration in large-deal wins compresses the multiple "
                "well before it compresses earnings.",
                "The Technical Analyst's bullish momentum read ignores "
                "that volumes have thinned on recent up-days, a classic "
                "warning sign of a rally running on fewer committed "
                "buyers.",
                "Client concentration in BFSI and North American "
                "discretionary spend leaves the order book more exposed "
                "to a Western recession than the Macro Economist's "
                "generic 'resilient IT demand' framing acknowledges.",
            ],
            "challenged_agents": ["fundamental_analyst", "technical_analyst"],
            "overlooked_risks": [
                "Wage inflation in niche AI/cloud skill categories could "
                "compress operating margins faster than pricing power "
                "can offset it.",
                "A weakening rupee helps reported margins but masks flat "
                "or declining dollar-denominated realisation per "
                "billed hour.",
            ],
            "bear_conviction": 6,
            "strongest_argument": (
                "Free cash flow conversion has declined for three "
                "straight years despite a rising headline fundamental "
                "score -- the quality of earnings is quietly eroding "
                "under a still-strong-looking surface."
            ),
            "summary": (
                "The bull case is directionally sound but is pricing in "
                "flawless execution; deteriorating FCF conversion and "
                "thinning volume on rallies are the two threads worth "
                "watching most closely."
            ),
        },
        "debate_rounds": (
            {
                "round_number": 1,
                "agent_responses": {
                    "fundamental": (
                        "Fundamental Analyst acknowledges the Contrarian's "
                        "challenge but maintains its original assessment "
                        "stands on the available evidence."
                    ),
                    "technical": (
                        "Technical Analyst acknowledges the Contrarian's "
                        "challenge but maintains its original assessment "
                        "stands on the available evidence."
                    ),
                    "sentiment": (
                        "News Sentiment Agent reaffirms its prior "
                        "position: sentiment remains positive on recent "
                        "large-deal announcements."
                    ),
                    "macro": (
                        "Macro Economist reaffirms its prior position: "
                        "IT services demand remains resilient into next "
                        "fiscal year."
                    ),
                    "risk": (
                        "Risk Officer has no position this round " "(data unavailable)."
                    ),
                },
                "contrarian": (
                    "Free cash flow conversion has declined for three "
                    "straight years despite a rising headline "
                    "fundamental score."
                ),
                "completed_at": "2026-06-01T09:15:00Z",
            },
            {
                "round_number": 2,
                "agent_responses": {
                    "fundamental": (
                        "Fundamental Analyst concedes the Contrarian's "
                        "challenge raises a material point and "
                        "acknowledges elevated uncertainty in its "
                        "original assessment."
                    ),
                    "technical": (
                        "Technical Analyst concedes the Contrarian's "
                        "challenge raises a material point and "
                        "acknowledges elevated uncertainty in its "
                        "original assessment."
                    ),
                    "sentiment": (
                        "News Sentiment Agent reaffirms its prior "
                        "position: sentiment remains positive on recent "
                        "large-deal announcements."
                    ),
                    "macro": (
                        "Macro Economist reaffirms its prior position: "
                        "IT services demand remains resilient into next "
                        "fiscal year."
                    ),
                    "risk": (
                        "Risk Officer flags client concentration in "
                        "BFSI and North American discretionary spend as "
                        "a monitorable but not yet critical risk."
                    ),
                },
                "contrarian": (
                    "Valuation already prices in several more years of "
                    "double-digit growth, leaving little room for a "
                    "deceleration in large-deal wins."
                ),
                "completed_at": "2026-06-01T09:16:30Z",
            },
        ),
        "decision": {
            "agent_name": "portfolio_manager",
            "verdict": "BUY",
            "conviction_score": 7,
            "price_target": "\u20b94,650 (12-month)",
            "time_horizon": "12 months",
            "executive_summary": (
                "A high-quality compounder with a durable order book, "
                "though the margin of safety has narrowed as valuation "
                "and earnings quality both moved in less favourable "
                "directions this year."
            ),
            "investment_thesis": (
                "Consistent large-deal wins and a resilient IT services "
                "demand backdrop support continued double-digit revenue "
                "growth, even as near-term multiple expansion looks "
                "unlikely."
            ),
            "bull_case": (
                "Market-leading scale, diversified vertical exposure, "
                "and a track record of margin discipline through prior "
                "demand cycles."
            ),
            "bear_case": (
                "Declining free cash flow conversion and full valuation "
                "leave little room for execution missteps or a Western "
                "demand slowdown."
            ),
            "risk_summary": (
                "Client concentration in BFSI/North America, wage "
                "inflation in scarce skill categories, and a valuation "
                "that assumes continued flawless execution."
            ),
            "valuation_summary": (
                "Trading near the upper end of its historical PE band; "
                "DCF suggests modest upside on base-case assumptions "
                "only."
            ),
            "key_risks": [
                "Declining FCF conversion despite a strong headline score",
                "Full valuation leaves little room for a growth miss",
                "Client concentration in BFSI and North America",
            ],
            "key_catalysts": [
                "Continued large-deal momentum",
                "AI/cloud services mix shift supporting realisation",
            ],
            "contrarian_response": (
                "The Contrarian's point on eroding cash conversion is "
                "well taken, and it is the single biggest reason "
                "conviction here is a 7 rather than higher -- but "
                "management's explicit commentary on elevated near-term "
                "capex, plus a balance sheet with ample net cash, "
                "supports reading this as a reinvestment phase rather "
                "than a structural deterioration, so the position stays "
                "a BUY with a tighter watch on the next two quarters' "
                "cash flow trend."
            ),
            "debate_rounds_used": 2,
            "agent_weights": {
                "fundamental_analyst": 0.25,
                "technical_analyst": 0.1,
                "news_sentiment": 0.1,
                "macro_economist": 0.1,
                "risk_officer": 0.15,
                "valuation_agent": 0.1,
                "contrarian_investor": 0.2,
            },
            "summary": (
                "TCS: BUY with conviction 7/10 -- strong franchise, "
                "narrowing margin of safety"
            ),
        },
        "rationale": (
            "The 'good' baseline case: 4 distinct counter-arguments, a "
            "2-round debate with 4-5 substantive agent responses per "
            "round, and a PM contrarian_response that engages with (not "
            "echoes) the Contrarian's strongest point."
        ),
    },
    {
        "name": "vodafone_idea_bear_case_confirmed",
        "contrarian": {
            "agent_name": "contrarian_investor",
            "counter_arguments": [
                "Even the Fundamental Analyst's cautious score understates "
                "the going-concern risk implied by negative net worth and "
                "AGR dues that dwarf the company's market capitalisation.",
                "Government equity conversion dilutes existing "
                "shareholders substantially and does not, by itself, "
                "resolve the underlying operating cash flow shortfall.",
                "Subscriber losses to two better-capitalised rivals show "
                "no sign of stabilising, which directly undermines any "
                "recovery thesis built on ARPU growth alone.",
                "The Valuation Agent's peer-multiple approach is not "
                "meaningful here -- a company with negative equity value "
                "cannot be sensibly benchmarked against solvent telecom "
                "peers on EV/EBITDA.",
                "Promoter support has been reactive and partial to date, "
                "not proactive, which is a weak foundation for a "
                "turnaround thesis to stand on.",
            ],
            "challenged_agents": ["fundamental_analyst", "valuation_agent"],
            "overlooked_risks": [
                "A further spectrum payment obligation could force "
                "another capital raise on dilutive terms within the next "
                "two fiscal years.",
            ],
            "bear_conviction": 9,
            "strongest_argument": (
                "Negative net worth combined with AGR dues that dwarf "
                "the market capitalisation makes this fundamentally a "
                "going-concern situation, not a normal cyclical "
                "turnaround case."
            ),
            "summary": (
                "This is one of the rare cases where the bear case is "
                "simply correct on the fundamentals -- the debate here "
                "is about degree of distress, not direction."
            ),
        },
        "debate_rounds": (
            {
                "round_number": 1,
                "agent_responses": {
                    "fundamental": (
                        "Fundamental Analyst concedes the Contrarian's "
                        "challenge raises a material point and "
                        "acknowledges elevated uncertainty in its "
                        "original assessment."
                    ),
                    "technical": (
                        "Technical Analyst reaffirms its prior position: "
                        "price action remains highly volatile and "
                        "news-driven."
                    ),
                    "sentiment": (
                        "News Sentiment Agent reaffirms its prior "
                        "position: coverage is dominated by dues and "
                        "capital-raise headlines."
                    ),
                    "macro": (
                        "Macro Economist reaffirms its prior position: "
                        "sector-wide tariff hikes offer some relief but "
                        "not enough to close the funding gap alone."
                    ),
                    "risk": (
                        "Risk Officer has no position this round " "(data unavailable)."
                    ),
                },
                "contrarian": (
                    "Negative net worth combined with AGR dues that "
                    "dwarf the market capitalisation makes this "
                    "fundamentally a going-concern situation."
                ),
                "completed_at": "2026-06-02T11:02:00Z",
            },
        ),
        "decision": {
            "agent_name": "portfolio_manager",
            "verdict": "SELL",
            "conviction_score": 8,
            "price_target": None,
            "time_horizon": "quarterly review (3 months)",
            "executive_summary": (
                "A distressed telecom operator whose going-concern risk "
                "outweighs any tariff-hike-driven recovery narrative in "
                "the near term."
            ),
            "investment_thesis": (
                "Negative net worth and dues obligations exceeding "
                "market capitalisation make the equity a speculative "
                "call option on further government support, not a "
                "fundamentally-grounded investment case."
            ),
            "bull_case": (
                "Tariff hikes across the sector and continued government "
                "equity conversion could buy enough runway for "
                "subscriber losses to stabilise."
            ),
            "bear_case": (
                "Negative net worth, unresolved AGR dues, and "
                "accelerating subscriber losses to better-capitalised "
                "rivals leave no clear fundamental floor under the "
                "stock."
            ),
            "risk_summary": (
                "Going-concern risk, further dilutive capital raises, "
                "and continued subscriber attrition are the dominant, "
                "not secondary, risks here."
            ),
            "valuation_summary": (
                "Standard peer-multiple valuation is not meaningful "
                "given negative net worth; any price reflects option "
                "value on continued government support, not enterprise "
                "cash flows."
            ),
            "key_risks": [
                "Going-concern risk from negative net worth",
                "Further dilutive capital raises",
                "Accelerating subscriber losses",
            ],
            "key_catalysts": [
                "Additional government relief measures",
            ],
            "contrarian_response": (
                "The Contrarian's framing is accepted in full here: this "
                "is a going-concern situation first and a valuation "
                "question a distant second, which is exactly why the "
                "committee is not attempting to assign a conventional "
                "price target and instead recommends avoiding new "
                "positions pending a credible resolution of the dues "
                "overhang."
            ),
            "debate_rounds_used": 1,
            "agent_weights": {
                "fundamental_analyst": 0.15,
                "technical_analyst": 0.05,
                "news_sentiment": 0.1,
                "macro_economist": 0.1,
                "risk_officer": 0.15,
                "valuation_agent": 0.05,
                "contrarian_investor": 0.4,
            },
            "summary": (
                "Vodafone Idea: SELL with conviction 8/10 -- "
                "going-concern risk dominates"
            ),
        },
        "rationale": (
            "A SELL-verdict case with only 1 debate round (bear_conviction "
            "9 is below the design's own re-debate trigger in some "
            "topologies, or the committee converged quickly) -- checks "
            "the eval doesn't assume every passing snapshot needs 2 "
            "rounds, and that PM 'agreeing with' the Contrarian still "
            "counts as genuinely engaging with the debate, not just "
            "rubber-stamping a challenge it disagrees with."
        ),
    },
    {
        "name": "hindunilvr_moderate_debate",
        "contrarian": {
            "agent_name": "contrarian_investor",
            "counter_arguments": [
                "Premium valuation multiples assume continued rural "
                "demand recovery that has been repeatedly delayed over "
                "the past several quarters.",
                "Private-label competition in home and personal care is "
                "structurally different from prior competitive cycles "
                "and may permanently cap pricing power in core "
                "categories.",
                "Input cost tailwinds that have supported recent margin "
                "expansion are unlikely to repeat at the same magnitude "
                "next fiscal year.",
            ],
            "challenged_agents": ["valuation_agent"],
            "overlooked_risks": [
                "Regional quick-commerce platforms are shifting share "
                "away from traditional general trade in ways the "
                "current distribution-strength thesis doesn't fully "
                "price in.",
            ],
            "bear_conviction": 4,
            "strongest_argument": (
                "Margin expansion has leaned heavily on temporary input "
                "cost tailwinds rather than durable pricing power, so "
                "the current premium multiple may be capitalising a "
                "margin level that mean-reverts lower."
            ),
            "summary": (
                "A mild disagreement rather than a full bear case -- the "
                "franchise quality is not in question, but the current "
                "multiple leaves limited room for a margin normalisation."
            ),
        },
        "debate_rounds": (
            {
                "round_number": 1,
                "agent_responses": {
                    "fundamental": (
                        "Fundamental Analyst reaffirms its prior "
                        "position: margin expansion and ROE remain "
                        "best-in-class for the sector."
                    ),
                    "technical": (
                        "Technical Analyst reaffirms its prior position: "
                        "price trend remains range-bound with low "
                        "volatility."
                    ),
                    "sentiment": (
                        "News Sentiment Agent reaffirms its prior "
                        "position: coverage is broadly neutral to "
                        "positive."
                    ),
                    "macro": (
                        "Macro Economist reaffirms its prior position: "
                        "rural demand recovery remains gradual but "
                        "intact."
                    ),
                    "risk": (
                        "Risk Officer has no position this round " "(data unavailable)."
                    ),
                },
                "contrarian": (
                    "Margin expansion has leaned heavily on temporary "
                    "input cost tailwinds rather than durable pricing "
                    "power."
                ),
                "completed_at": "2026-06-03T10:00:00Z",
            },
        ),
        "decision": {
            "agent_name": "portfolio_manager",
            "verdict": "HOLD",
            "conviction_score": 6,
            "price_target": "\u20b92,650 (12-month)",
            "time_horizon": "12 months",
            "executive_summary": (
                "A high-quality FMCG franchise trading at a valuation "
                "that already reflects most of the near-term good news."
            ),
            "investment_thesis": (
                "Franchise strength and distribution reach remain intact, "
                "but the risk-reward is balanced rather than skewed to "
                "the upside at current multiples."
            ),
            "bull_case": (
                "Best-in-class ROE, gradual rural demand recovery, and "
                "resilient category leadership across home and personal "
                "care."
            ),
            "bear_case": (
                "Margin expansion has relied on temporary input cost "
                "tailwinds, and quick-commerce is reshaping distribution "
                "economics in ways not yet fully reflected in the "
                "thesis."
            ),
            "risk_summary": (
                "Input cost normalisation, private-label competition, "
                "and channel-mix shift toward quick-commerce are the "
                "top monitorables."
            ),
            "valuation_summary": (
                "Premium multiple versus historical average leaves "
                "limited margin of safety if input costs normalise."
            ),
            "key_risks": [
                "Margin mean-reversion as input cost tailwinds fade",
                "Quick-commerce share shift from general trade",
            ],
            "key_catalysts": [
                "Faster-than-expected rural demand recovery",
            ],
            "contrarian_response": (
                "The Contrarian is right that recent margin gains lean "
                "on cost tailwinds rather than pricing power, which is "
                "the core reason this call is a HOLD rather than a BUY "
                "despite genuinely strong franchise fundamentals -- the "
                "committee wants to see at least one more quarter of "
                "margin resilience once input costs normalise before "
                "adding conviction."
            ),
            "debate_rounds_used": 1,
            "agent_weights": {
                "fundamental_analyst": 0.25,
                "technical_analyst": 0.1,
                "news_sentiment": 0.1,
                "macro_economist": 0.15,
                "risk_officer": 0.1,
                "valuation_agent": 0.15,
                "contrarian_investor": 0.15,
            },
            "summary": (
                "HUL: HOLD with conviction 6/10 -- quality franchise, " "full valuation"
            ),
        },
        "rationale": (
            "A HOLD-verdict case with low bear_conviction (4) -- checks "
            "the eval doesn't require a high-conviction Contrarian to "
            "still count as 'disagreeing': 3 distinct counter-arguments "
            "at mild conviction is still a genuine disagreement, not a "
            "rubber stamp."
        ),
    },
    {
        "name": "wipro_neutral_hold_debate",
        "contrarian": {
            "agent_name": "contrarian_investor",
            "counter_arguments": [
                "Multi-year revenue growth has consistently lagged the "
                "two largest peers, and nothing in the current deal "
                "pipeline suggests that gap is closing.",
                "Recent leadership changes introduce execution risk right "
                "as the company attempts a strategic repositioning "
                "toward higher-margin consulting work.",
                "The Technical Analyst's neutral read undersells "
                "persistent relative underperformance versus the "
                "sector index over the trailing two years.",
            ],
            "challenged_agents": ["technical_analyst"],
            "overlooked_risks": [
                "Integration risk from recent acquisitions has not yet "
                "shown up in reported margins but could weigh on them "
                "over the next few quarters.",
            ],
            "bear_conviction": 5,
            "strongest_argument": (
                "Revenue growth has structurally lagged the two largest "
                "peers for several years running, and the current deal "
                "pipeline gives no concrete evidence that gap is about "
                "to close."
            ),
            "summary": (
                "Not a company in distress, but a persistent growth-gap "
                "story that the current valuation doesn't obviously "
                "compensate for."
            ),
        },
        "debate_rounds": (
            {
                "round_number": 1,
                "agent_responses": {
                    "fundamental": (
                        "Fundamental Analyst reaffirms its prior "
                        "position: balance sheet remains conservative "
                        "with low leverage."
                    ),
                    "technical": (
                        "Technical Analyst acknowledges the Contrarian's "
                        "challenge but maintains its original assessment "
                        "stands on the available evidence."
                    ),
                    "sentiment": (
                        "News Sentiment Agent reaffirms its prior "
                        "position: coverage is mixed, centred on "
                        "leadership transition commentary."
                    ),
                    "macro": (
                        "Macro Economist reaffirms its prior position: "
                        "sector-wide IT demand outlook is stable."
                    ),
                    "risk": (
                        "Risk Officer has no position this round " "(data unavailable)."
                    ),
                },
                "contrarian": (
                    "Revenue growth has structurally lagged the two "
                    "largest peers for several years running."
                ),
                "completed_at": "2026-06-04T14:20:00Z",
            },
        ),
        "decision": {
            "agent_name": "portfolio_manager",
            "verdict": "HOLD",
            "conviction_score": 5,
            "price_target": "\u20b9520 (12-month)",
            "time_horizon": "quarterly review (3 months)",
            "executive_summary": (
                "A financially conservative IT services company facing "
                "a persistent growth gap versus larger peers, with "
                "leadership transition adding near-term uncertainty."
            ),
            "investment_thesis": (
                "Balance sheet strength provides downside protection, "
                "but a credible catalyst for closing the growth gap "
                "with larger peers has not yet materialised."
            ),
            "bull_case": (
                "Low leverage, ongoing repositioning toward "
                "higher-margin consulting work, and a valuation that "
                "already reflects the growth gap."
            ),
            "bear_case": (
                "Structural growth underperformance versus peers, "
                "leadership transition risk, and unproven integration of "
                "recent acquisitions."
            ),
            "risk_summary": (
                "Execution risk from leadership transition, acquisition "
                "integration risk, and continued relative growth "
                "underperformance."
            ),
            "valuation_summary": (
                "Trades at a discount to larger peers, which appears "
                "justified rather than an obvious value opportunity "
                "given the growth gap."
            ),
            "key_risks": [
                "Persistent growth underperformance versus peers",
                "Leadership transition execution risk",
                "Unproven acquisition integration",
            ],
            "key_catalysts": [
                "Successful repositioning toward higher-margin consulting",
            ],
            "contrarian_response": (
                "The Contrarian's point about a structural, multi-year "
                "growth gap versus peers is fair and is reflected "
                "directly in the modest conviction score here -- the "
                "committee sees enough balance-sheet cushion to avoid a "
                "SELL, but wants clear evidence of growth-gap narrowing "
                "before moving to a BUY."
            ),
            "debate_rounds_used": 1,
            "agent_weights": {
                "fundamental_analyst": 0.2,
                "technical_analyst": 0.15,
                "news_sentiment": 0.1,
                "macro_economist": 0.1,
                "risk_officer": 0.1,
                "valuation_agent": 0.15,
                "contrarian_investor": 0.2,
            },
            "summary": (
                "Wipro: HOLD with conviction 5/10 -- persistent growth "
                "gap versus peers"
            ),
        },
        "rationale": (
            "A genuinely uncertain HOLD case (conviction 5/10) -- checks "
            "the eval's checks hold even when the Portfolio Manager's "
            "own confidence is low, not just on high-conviction BUY/SELL "
            "calls."
        ),
    },
    {
        "name": "tata_steel_cyclical_debate",
        "contrarian": {
            "agent_name": "contrarian_investor",
            "counter_arguments": [
                "Current spreads between input costs and realisations "
                "are near cyclical highs, and the Fundamental Analyst's "
                "score does not adequately discount for reversion as the "
                "cycle turns.",
                "European operations continue to be a structural drag on "
                "consolidated returns, and no credible near-term "
                "resolution has been presented by management.",
                "Elevated net debt leaves limited flexibility to sustain "
                "capital returns to shareholders through the next "
                "downturn in the steel cycle.",
                "The Macro Economist's China-demand-recovery assumption "
                "is the single largest swing factor in the whole thesis "
                "and is treated with more confidence than the underlying "
                "data supports.",
            ],
            "challenged_agents": ["fundamental_analyst", "macro_economist"],
            "overlooked_risks": [
                "A sharp swing in Chinese export dumping could compress "
                "domestic spreads faster than the current base case "
                "assumes.",
            ],
            "bear_conviction": 7,
            "strongest_argument": (
                "Current input-to-output price spreads are near cyclical "
                "highs, and elevated net debt leaves little room to "
                "sustain shareholder returns once the cycle inevitably "
                "turns."
            ),
            "summary": (
                "A classic late-cycle setup: strong trailing numbers "
                "masking a balance sheet that is not well positioned "
                "for the next downturn."
            ),
        },
        "debate_rounds": (
            {
                "round_number": 1,
                "agent_responses": {
                    "fundamental": (
                        "Fundamental Analyst acknowledges the Contrarian's "
                        "challenge but maintains its original assessment "
                        "stands on the available evidence."
                    ),
                    "technical": (
                        "Technical Analyst reaffirms its prior position: "
                        "price momentum remains positive near-term."
                    ),
                    "sentiment": (
                        "News Sentiment Agent reaffirms its prior "
                        "position: coverage centres on capacity "
                        "expansion announcements."
                    ),
                    "macro": (
                        "Macro Economist acknowledges the Contrarian's "
                        "challenge but maintains its original assessment "
                        "stands on the available evidence."
                    ),
                    "risk": (
                        "Risk Officer has no position this round " "(data unavailable)."
                    ),
                },
                "contrarian": (
                    "Current input-to-output price spreads are near "
                    "cyclical highs, and elevated net debt leaves little "
                    "room to sustain shareholder returns once the cycle "
                    "turns."
                ),
                "completed_at": "2026-06-05T08:45:00Z",
            },
            {
                "round_number": 2,
                "agent_responses": {
                    "fundamental": (
                        "Fundamental Analyst concedes the Contrarian's "
                        "challenge raises a material point and "
                        "acknowledges elevated uncertainty in its "
                        "original assessment."
                    ),
                    "technical": (
                        "Technical Analyst reaffirms its prior position: "
                        "price momentum remains positive near-term."
                    ),
                    "sentiment": (
                        "News Sentiment Agent reaffirms its prior "
                        "position: coverage centres on capacity "
                        "expansion announcements."
                    ),
                    "macro": (
                        "Macro Economist concedes the Contrarian's "
                        "challenge raises a material point and "
                        "acknowledges elevated uncertainty in its "
                        "original assessment."
                    ),
                    "risk": (
                        "Risk Officer flags elevated net debt as a "
                        "monitorable balance-sheet risk heading into a "
                        "potential cycle downturn."
                    ),
                },
                "contrarian": (
                    "European operations continue to be a structural "
                    "drag on consolidated returns with no credible "
                    "near-term resolution presented by management."
                ),
                "completed_at": "2026-06-05T08:47:15Z",
            },
        ),
        "decision": {
            "agent_name": "portfolio_manager",
            "verdict": "HOLD",
            "conviction_score": 5,
            "price_target": "\u20b9165 (12-month)",
            "time_horizon": "3-6 months",
            "executive_summary": (
                "Strong trailing cyclical numbers against a balance "
                "sheet and cycle-timing setup that warrant caution "
                "rather than conviction in either direction."
            ),
            "investment_thesis": (
                "Near-cyclical-high spreads have driven strong recent "
                "results, but elevated net debt and an unresolved "
                "European drag limit the case for adding exposure at "
                "this point in the cycle."
            ),
            "bull_case": (
                "Domestic capacity expansion and currently favourable "
                "spreads support strong near-term cash generation."
            ),
            "bear_case": (
                "Cyclically elevated spreads are likely to mean-revert, "
                "and elevated net debt leaves limited room to sustain "
                "capital returns through the next downturn."
            ),
            "risk_summary": (
                "Cycle-timing risk, elevated net debt, an unresolved "
                "European drag, and a China-demand assumption that "
                "carries more uncertainty than the base case reflects."
            ),
            "valuation_summary": (
                "Reasonable on trailing metrics, but trailing metrics "
                "themselves reflect a cyclically favourable spread "
                "environment that is unlikely to persist unchanged."
            ),
            "key_risks": [
                "Cyclical spread mean-reversion",
                "Elevated net debt limiting capital-return flexibility",
                "Unresolved European operations drag",
            ],
            "key_catalysts": [
                "Faster-than-expected China demand recovery",
            ],
            "contrarian_response": (
                "The committee agrees with the Contrarian that today's "
                "spreads are unusually favourable and shouldn't be "
                "extrapolated forward, which is precisely why this call "
                "is a HOLD rather than a BUY despite genuinely strong "
                "trailing results -- the balance sheet needs to "
                "delever further before the risk-reward turns clearly "
                "attractive again."
            ),
            "debate_rounds_used": 2,
            "agent_weights": {
                "fundamental_analyst": 0.2,
                "technical_analyst": 0.1,
                "news_sentiment": 0.05,
                "macro_economist": 0.15,
                "risk_officer": 0.15,
                "valuation_agent": 0.1,
                "contrarian_investor": 0.25,
            },
            "summary": "Tata Steel: HOLD with conviction 5/10 -- late-cycle caution",
        },
        "rationale": (
            "A cyclical/commodity name with a high bear_conviction (7) "
            "and a genuine 2-round debate where TWO different agents "
            "concede across the two rounds -- checks the eval handles a "
            "richer, higher-conviction disagreement case with more "
            "moving parts than the other 4 snapshots."
        ),
    },
)

__all__ = ["DebateSnapshotExample", "DEBATE_EVAL_DATASET"]
