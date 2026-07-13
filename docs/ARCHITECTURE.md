# AIRP — System Architecture

> **Audience:** Engineers contributing to AIRP, or technical reviewers evaluating the project.
> This document describes the complete system architecture — layers, components, data flow,
> state design, and the rationale behind every major technical decision.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Layer 1 — Frontend (React)](#2-layer-1--frontend-react)
3. [Layer 2 — Backend API (FastAPI)](#3-layer-2--backend-api-fastapi)
4. [Layer 3 — Agent Orchestration (LangGraph)](#4-layer-3--agent-orchestration-langgraph)
5. [Layer 4 — Data & Storage](#5-layer-4--data--storage)
6. [Layer 5 — Observability & DevOps](#6-layer-5--observability--devops)
7. [Request Flow (End-to-End)](#7-request-flow-end-to-end)
8. [InvestmentState — The Shared Pipeline State](#8-investmentstate--the-shared-pipeline-state)
9. [The Debate Engine](#9-the-debate-engine)
10. [Key Design Decisions](#10-key-design-decisions)
11. [Deployment Architecture](#11-deployment-architecture)

---

## 1. Architecture Overview

AIRP is a five-layer system. Each layer has a single, well-defined responsibility.
No layer reaches across more than one layer boundary.

```
┌──────────────────────────────────────────────────────────────────┐
│  LAYER 1 — User Interface                                        │
│  React 18 · TypeScript · Tailwind CSS · Vite · Deployed: Vercel │
├──────────────────────────────────────────────────────────────────┤
│  LAYER 2 — Backend API                                           │
│  FastAPI · Python 3.11 · WebSocket · Deployed: Render           │
├──────────────────────────────────────────────────────────────────┤
│  LAYER 3 — Agent Orchestration                                   │
│  LangGraph StateGraph · 8 AI Agents · Claude API backbone        │
├──────────────────────────────────────────────────────────────────┤
│  LAYER 4 — Data & Storage                                        │
│  PostgreSQL (Neon) · ChromaDB · Redis (Upstash) · Market APIs   │
├──────────────────────────────────────────────────────────────────┤
│  LAYER 5 — Observability & DevOps                                │
│  LangSmith · GitHub Actions · Docker · Vercel · Render          │
└──────────────────────────────────────────────────────────────────┘
```

The full architecture diagram (draw.io source) lives at `docs/AIRP_Architecture.drawio`.

---

## 2. Layer 1 — Frontend (React)

### Responsibility

All user interaction. Renders the UI, connects to the backend via HTTP and
WebSocket, and displays live agent progress as the pipeline runs.

### Components

| Component                      | Description                                                           |
| ------------------------------ | --------------------------------------------------------------------- |
| **Landing page**               | Hero, feature highlights, 8-agent diagram, demo CTA                   |
| **Auth pages**                 | Login and Register with `react-hook-form` + `zod` validation          |
| **Dashboard**                  | User's analysis history — company, date, verdict badge, risk score    |
| **Analysis input**             | Company name autocomplete (top 50 NSE stocks), optional PDF upload    |
| **Live agent progress viewer** | WebSocket consumer — card per agent, animated state transitions       |
| **Debate viewer**              | Timeline UI showing agents arguing, colour-coded per agent            |
| **Results page**               | Final verdict panel, bull vs bear cases, conviction gauge             |
| **Charts**                     | Stock price, revenue trend, P/E vs peers, sentiment gauge, risk radar |
| **Investment Memo viewer**     | Full memo with collapsible sections + PDF download button             |
| **Compare page**               | Side-by-side analysis of two companies                                |

### Technology choices

| Technology            | Version   | Reason                                                          |
| --------------------- | --------- | --------------------------------------------------------------- |
| React                 | 18        | Concurrent mode for smooth real-time updates                    |
| TypeScript            | 5.x       | Catches integration bugs with backend schemas at compile time   |
| Vite                  | 5.x       | Instant HMR — much faster than CRA during development           |
| Tailwind CSS          | 3.x       | Utility-first — fast UI iteration without context-switching     |
| React Query           | 5.x       | Handles server state, loading, error, and cache automatically   |
| Recharts              | 2.x       | Composable React chart library with good TypeScript support     |
| React Hook Form + Zod | 7.x / 3.x | Minimal re-renders; schema validation shared with backend types |
| WebSocket (native)    | —         | No extra library needed for agent event streaming               |

### State management strategy

- **Server state** (analyses, history, agent results): React Query
- **UI state** (form inputs, modal open/close, tabs): `useState` / `useReducer`
- **WebSocket state** (live agent events): custom `useWebSocket` hook
- **Auth state** (JWT, user identity): Clerk + React Context

---

## 3. Layer 2 — Backend API (FastAPI)

### Responsibility

Exposes the agent pipeline to the frontend via REST and WebSocket.
Handles authentication, input validation, background pipeline execution,
file uploads, and result retrieval.

### Route structure

```
POST   /api/v1/auth/register          → create user account
POST   /api/v1/auth/login             → return JWT
GET    /api/v1/auth/me                → current user profile

POST   /api/v1/analysis/start         → validate input, create job, trigger pipeline
GET    /api/v1/analysis/{id}/status   → current phase, completed nodes, progress %
GET    /api/v1/analysis/{id}/result   → full InvestmentDecision JSON
GET    /api/v1/analysis/{id}/memo/pdf → download Investment Memo PDF
WS     /api/v1/analysis/{id}/stream   → real-time agent events (WebSocket)

GET    /api/v1/history                → user's last 20 analyses (paginated)

POST   /api/v1/documents/upload       → accept PDF, extract text, embed into ChromaDB

GET    /health                        → {"status": "ok"} — used by Render health check
```

### FastAPI project structure

```
backend/
├── routers/
│   ├── auth.py           # /auth/* endpoints
│   ├── analysis.py       # /analysis/* + WebSocket endpoint
│   ├── documents.py      # /documents/upload
│   └── history.py        # /history
├── services/
│   ├── analysis_service.py    # orchestrates pipeline trigger + status updates
│   ├── document_service.py    # PDF text extraction + ChromaDB ingestion
│   └── auth_service.py        # JWT creation, password hashing
├── models/
│   ├── orm.py            # SQLAlchemy models (User, Analysis, AgentOutput, Memo)
│   └── schemas.py        # Pydantic request/response schemas
├── dependencies.py       # FastAPI dependency injection (get_db, get_current_user)
├── config.py             # Settings from environment variables (pydantic-settings)
└── main.py               # App factory, CORS, router registration, lifespan events
```

### Background task pattern

The analysis pipeline is CPU and I/O intensive (~90 seconds). It runs as a
FastAPI background task so the `POST /analysis/start` endpoint returns a
`job_id` in under 200ms while the pipeline runs asynchronously.

```python
# routers/analysis.py (simplified)
@router.post("/start")
async def start_analysis(
    body: AnalysisRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnalysisStartResponse:
    analysis = await analysis_service.create_job(db, user.id, body.company)
    background_tasks.add_task(run_pipeline, analysis.id, body.company)
    return AnalysisStartResponse(job_id=analysis.id)
```

### WebSocket streaming pattern

The pipeline emits events at each node completion. The WebSocket endpoint
subscribes to those events and pushes them to the connected browser.

```
Agent completes → publishes event to Redis pub/sub channel
                → WebSocket handler reads from channel
                → pushes JSON event to browser
```

Event schema per agent:

```json
{
  "agent": "fundamental_analyst",
  "status": "complete",
  "duration_ms": 12400,
  "output_preview": "Score: 7/10 — Strong revenue growth, healthy FCF...",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

---

## 4. Layer 3 — Agent Orchestration (LangGraph)

### Why LangGraph, not plain LangChain agents

LangChain agents run a single agent in a loop until a stopping condition.
LangGraph enables:

1. **Multiple agents sharing a typed state object** — each agent reads prior outputs
2. **Parallel execution** — the four research agents run simultaneously via the Send API
3. **Cyclical workflows** — the debate loop runs 2 rounds before proceeding
4. **Conditional routing** — different paths based on intermediate results
5. **Stateful checkpointing** — persist state to PostgreSQL after every node

### The 8-Agent Investment Committee

| #   | Agent                    | Mandate                                       | Primary Tools           | Output Type           |
| --- | ------------------------ | --------------------------------------------- | ----------------------- | --------------------- |
| 1   | **Fundamental Analyst**  | Revenue, margins, FCF, debt over 4 years      | yFinance, Alpha Vantage | `FundamentalAnalysis` |
| 2   | **Technical Analyst**    | Price trends, RSI, 50d/200d MA, momentum      | yFinance OHLCV          | `TechnicalAnalysis`   |
| 3   | **News Sentiment Agent** | Last 30 days news, red flag detection, RAG    | NewsAPI, ChromaDB       | `SentimentAnalysis`   |
| 4   | **Macro Economist**      | RBI rates, inflation, GDP, sector outlook     | RBI scraper, macro DB   | `MacroAnalysis`       |
| 5   | **Risk Officer**         | Governance, fraud indicators, regulatory risk | All prior agent outputs | `RiskAnalysis`        |
| 6   | **Contrarian Investor**  | Find flaws in every bull thesis               | Full debate state       | `ContrarianReport`    |
| 7   | **Valuation Agent**      | DCF, PE/PB/EV-EBITDA vs peers                 | Screener.in, yFinance   | `ValuationOutput`     |
| 8   | **Portfolio Manager**    | Synthesise full debate → final verdict        | Full pipeline state     | `InvestmentDecision`  |

### Pipeline execution flow

```
                    ┌─────────────────┐
                    │ Planner node    │
                    │ Resolve ticker  │
                    │ Init state      │
                    └────────┬────────┘
                             │ Send API (parallel)
          ┌──────────────────┼──────────────────┐
          │                  │                  │
   ┌──────┴──────┐   ┌───────┴──────┐   ┌───────┴──────┐   ┌──────────────┐
   │ Fundamental │   │  Technical   │   │    News      │   │    Macro     │
   │  Analyst    │   │  Analyst     │   │  Sentiment   │   │  Economist   │
   └──────┬──────┘   └───────┬──────┘   └───────┬──────┘   └──────┬───────┘
          └──────────────────┴──────────────────┴──────────────────┘
                             │ merge outputs into state
                    ┌────────┴────────┐
                    │  Debate Round 1 │ ← agents respond to each other
                    └────────┬────────┘
                    ┌────────┴────────┐
                    │  Debate Round 2 │ ← Contrarian challenges consensus
                    └────────┬────────┘
                             │ sequential
                    ┌────────┴────────┐
                    │  Risk Officer   │
                    └────────┬────────┘
                    ┌────────┴────────┐
                    │ Valuation Agent │
                    └────────┬────────┘
                    ┌────────┴────────┐
                    │ Portfolio Mgr   │
                    └────────┬────────┘
                    ┌────────┴────────┐
                    │ Memo Generator  │
                    │ (PDF export)    │
                    └─────────────────┘
```

### Conditional routing

The graph has two conditional edges:

1. **Empty data guard** — if `fetch_financials` returns no data (delisted ticker,
   API failure), the planner routes to an `error_handler` node instead of
   continuing the pipeline.

2. **Sentiment escalation** — if `sentiment.score < -0.8` (strongly negative news),
   the graph adds an extra research round before the debate begins.

### State persistence

After every node completes, `InvestmentState` is serialised to JSON and saved
to the `analyses` table in PostgreSQL. If a node fails mid-pipeline, the graph
can be resumed from the last successfully persisted checkpoint — no rerunning
of completed agents.

---

## 5. Layer 4 — Data & Storage

### PostgreSQL (Neon)

Primary relational database. Stores all persistent data.

| Table              | Purpose                                                     |
| ------------------ | ----------------------------------------------------------- |
| `users`            | Account credentials, created_at                             |
| `analyses`         | Job records — company, status, timestamps, state checkpoint |
| `agent_outputs`    | Raw output per agent per analysis (JSONB)                   |
| `investment_memos` | Generated memo text (JSONB structured)                      |
| `documents`        | Uploaded PDF metadata — filename, company, embedding status |

Schema migrations managed by **Alembic**. Run `alembic upgrade head` to apply.

### ChromaDB (Vector Database)

Stores embeddings for RAG — retrieved by the News Sentiment Agent when
searching for relevant past context about a company.

| Collection             | Contents                                       | Embedding model                            |
| ---------------------- | ---------------------------------------------- | ------------------------------------------ |
| `news_articles`        | NewsAPI headlines + descriptions, last 30 days | `all-MiniLM-L6-v2` (sentence-transformers) |
| `earnings_transcripts` | Scraped Screener.in concall transcripts        | `all-MiniLM-L6-v2`                         |
| `uploaded_documents`   | User-uploaded annual reports and PDFs          | `all-MiniLM-L6-v2`                         |

ChromaDB runs locally in development (Docker volume). In production it is a
persistent Docker container on Render alongside the FastAPI service.

**Why sentence-transformers instead of OpenAI embeddings?** No per-token API
cost. The `all-MiniLM-L6-v2` model runs locally and produces high-quality
768-dimensional embeddings sufficient for financial document retrieval.

### Redis (Upstash)

Caches all external API responses to protect free tier rate limits and reduce
pipeline latency.

| Cache key pattern           | TTL      | What is cached                             |
| --------------------------- | -------- | ------------------------------------------ |
| `stock:{ticker}:ohlcv`      | 15 min   | yFinance OHLCV data                        |
| `stock:{ticker}:financials` | 1 hour   | Income statement, balance sheet, cash flow |
| `news:{company}`            | 1 hour   | NewsAPI response for company name          |
| `macro:rbi`                 | 24 hours | RBI repo rate and inflation data           |
| `ratios:{ticker}`           | 1 hour   | PE, PB, ROE, ROCE, Debt/Equity             |

Redis also serves as the pub/sub broker between the pipeline background task
and the WebSocket endpoint (agent completion events).

### Market Data APIs

See [APIS.md](APIS.md) for full details. Brief summary:

| API           | Used by                                  | Data                                |
| ------------- | ---------------------------------------- | ----------------------------------- |
| yFinance      | Fundamental, Technical, Valuation agents | Prices, OHLCV, financials           |
| NewsAPI       | News Sentiment Agent                     | Company news headlines              |
| Alpha Vantage | Fundamental Agent (supplementary)        | Earnings, fundamentals              |
| Screener.in   | Valuation Agent                          | Indian peer comparison, transcripts |
| RBI scraper   | Macro Economist Agent                    | Repo rate, inflation                |

---

## 6. Layer 5 — Observability & DevOps

### LangSmith

Every LLM call, tool use, and agent execution is traced in LangSmith.

- **What is traced:** agent name, company ticker, prompt sent, response received,
  token count (input + output), latency, tool calls made
- **Tags per trace:** `agent:<name>`, `company:<ticker>`, `env:<dev|prod>`
- **Project naming:** `airp-dev` (development), `airp-prod` (production)
- **Evaluation suites:** Fundamental Analyst accuracy, Sentiment direction,
  Debate novelty, end-to-end latency (p50 < 90s target)

Enable/disable tracing without code change:

```bash
LANGCHAIN_TRACING_V2=true   # enable
LANGCHAIN_TRACING_V2=false  # disable (saves free quota during rapid iteration)
```

### GitHub Actions (CI/CD)

Every push to every branch triggers `.github/workflows/ci.yml`:

```
Push to any branch
  → Install Python deps
  → black --check backend/
  → isort --check backend/
  → flake8 backend/
  → mypy backend/
  → pytest (unit only, --cov-fail-under=85)
  → Install Node deps
  → tsc --noEmit
  → eslint --max-warnings 0
  → vite build
```

PRs to `main` must pass all checks. Merge is blocked otherwise.

### Docker (local development)

```bash
docker-compose up
```

Starts four services locally:

- `api` — FastAPI on port 8000
- `postgres` — PostgreSQL on port 5432
- `redis` — Redis on port 6379
- `chromadb` — ChromaDB on port 8001

The React frontend runs separately via `npm run dev` (port 5173) for hot reload.

---

## 7. Request Flow (End-to-End)

Complete trace of a single analysis from browser click to PDF download:

```
1.  User types "Infosys" and clicks "Start Analysis"
    → React: POST /api/v1/analysis/start {company: "Infosys"}

2.  FastAPI validates input, creates DB record, returns {job_id: "abc-123"}
    → Background task queued: run_pipeline("abc-123", "Infosys")
    → Response to browser in < 200ms

3.  React opens WebSocket: WS /api/v1/analysis/abc-123/stream

4.  LangGraph pipeline starts in background:
    → Planner node resolves "Infosys" → "INFY.NS"
    → Initialises InvestmentState
    → State saved to PostgreSQL

5.  Send API launches 4 agents in parallel:
    → Fundamental Analyst fetches financials via yFinance (or Redis cache)
    → Technical Analyst fetches OHLCV, computes RSI + moving averages
    → News Sentiment fetches NewsAPI + runs ChromaDB RAG search
    → Macro Economist scrapes RBI data
    → Each agent completion: publishes event to Redis pub/sub

6.  WebSocket handler reads Redis pub/sub → pushes to browser:
    → {"agent": "fundamental_analyst", "status": "complete", ...}
    → {"agent": "technical_analyst", "status": "complete", ...}
    → etc.
    → React updates: agent cards animate from "Thinking" → "Complete"

7.  Debate Round 1: each agent reads all others' outputs and responds
    → debate_rounds[0] appended to InvestmentState
    → State saved to PostgreSQL

8.  Debate Round 2: Contrarian reads full Round 1, challenges every bull thesis
    → debate_rounds[1] appended to InvestmentState

9.  Risk Officer runs: reads all research + debate outputs
    → RiskAnalysis saved to state

10. Valuation Agent runs: DCF + Screener.in peer comparison
    → ValuationOutput saved to state

11. Portfolio Manager reads complete state including full debate transcript
    → Produces InvestmentDecision: verdict, conviction, price target, memo

12. Memo Generator builds structured Investment Memo
    → WeasyPrint renders PDF
    → PDF stored; record updated in PostgreSQL

13. WebSocket sends final event: {"status": "complete", "job_id": "abc-123"}
    → WebSocket closes cleanly

14. React navigates to /analysis/abc-123/results
    → GET /api/v1/analysis/abc-123/result → full JSON
    → Renders results page, memo viewer, PDF download button
```

Total time from Step 1 to Step 13: **under 90 seconds**.

---

## 8. InvestmentState — The Shared Pipeline State

`InvestmentState` is a single `TypedDict` that flows through every node in the
LangGraph pipeline. Every agent reads from it and writes its output back to it.
No agent communicates directly with another — all communication is through state.

```python
class InvestmentState(TypedDict):
    # ── Input ──────────────────────────────────────────────────────────
    job_id: str
    company_name: str
    ticker: str
    uploaded_document_ids: list[str]  # ChromaDB doc IDs for RAG

    # ── Research phase ─────────────────────────────────────────────────
    fundamental_analysis: FundamentalAnalysis | None
    technical_analysis: TechnicalAnalysis | None
    sentiment_analysis: SentimentAnalysis | None
    macro_analysis: MacroAnalysis | None

    # ── Debate phase ───────────────────────────────────────────────────
    debate_rounds: list[DebateRound]   # grows with each round
    contrarian_report: ContrarianReport | None

    # ── Decision phase ─────────────────────────────────────────────────
    risk_analysis: RiskAnalysis | None
    valuation_output: ValuationOutput | None
    investment_decision: InvestmentDecision | None

    # ── Meta ───────────────────────────────────────────────────────────
    current_phase: str       # "research" | "debate" | "decision" | "complete"
    errors: list[str]        # non-fatal errors encountered during pipeline
    version: int             # incremented on each state update
```

State is persisted to PostgreSQL (JSONB column) after every node. The
`version` field enables optimistic locking to prevent race conditions on
concurrent state updates.

---

## 9. The Debate Engine

The debate engine is what distinguishes AIRP from a standard multi-agent system.

### How it works

After the four research agents complete, the graph enters a structured
`debate_loop` node that runs for a maximum of `MAX_DEBATE_ROUNDS = 2` iterations.

**Round 1 — Cross-agent responses:**
Each agent receives a context window containing all other agents' outputs and
generates a response: agreeing where evidence supports, or flagging disagreements.
All responses are appended to `debate_rounds[0]`.

**Round 2 — Contrarian challenge:**
The Contrarian Investor agent receives the full Round 1 transcript and attempts
to dismantle the emerging consensus. Its only job is to find overlooked risks,
challenge assumptions, and surface the bear case. Output goes into `contrarian_report`
and `debate_rounds[1]`.

**Termination condition:**
The loop terminates after `MAX_DEBATE_ROUNDS` regardless of consensus. There is
intentionally no automatic consensus detection — the Portfolio Manager is the
final authority on resolving disagreements.

### Portfolio Manager as final authority

The Portfolio Manager receives the complete `InvestmentState` including every
debate round. It is prompted to:

1. Summarise the bull case and bear case from the debate
2. Explicitly acknowledge the Contrarian's strongest arguments
3. Weigh them against the research agents' evidence
4. Deliver a BUY / HOLD / SELL verdict with a conviction score (1–10)

No single research agent has authority over the final decision. The Portfolio
Manager can and does override strong individual signals when the overall
evidence picture is mixed.

---

## 10. Key Design Decisions

### Why Claude API as the LLM backbone?

Every agent's system prompt and tool calls go through Claude. Claude was chosen
because it follows complex structured output instructions reliably, handles long
context windows well (useful for feeding the full debate transcript to the
Portfolio Manager), and is accessible via an existing Pro subscription.

Agents use `claude-haiku-4-20250514` during development (lower cost) and
`claude-sonnet-4-20250514` for production-quality demos.

### Why not a single LLM call?

A single LLM call with a long system prompt cannot:

- Run tasks in parallel
- Produce independently validated structured outputs per domain
- Simulate adversarial debate between genuinely distinct perspectives
- Be traced individually per agent in LangSmith

Multi-agent orchestration solves all four problems.

### Why Pydantic v2 output schemas?

Every agent's output is validated against a strict Pydantic model before being
written to state. This prevents:

- Agents returning unstructured prose instead of structured data
- Missing fields causing `KeyError` in downstream agents
- Type mismatches between agent output and the Investment Memo template

If an agent returns malformed output, Pydantic raises a `ValidationError` that
is caught at the node level, logged to LangSmith, and triggers the error handler.

### Why PostgreSQL for state persistence, not in-memory?

If the FastAPI process restarts mid-pipeline (Render free tier cold-start, OOM),
the pipeline would need to restart from scratch without persistence. PostgreSQL
checkpointing means the pipeline resumes from the last completed node — no
wasted LLM calls.

### Why Redis for WebSocket events instead of direct async queues?

FastAPI's background tasks run in the same process as the WebSocket endpoint.
Redis pub/sub decouples event emission (pipeline) from event consumption
(WebSocket), which is more resilient and allows future horizontal scaling if
needed.

---

## 11. Deployment Architecture

```
User's browser
     │
     │ HTTPS
     ▼
Vercel (CDN edge)
  React 18 SPA
  Static assets
     │
     │ HTTPS (REST) / WSS (WebSocket)
     ▼
Render (Web Service)
  FastAPI + Uvicorn
  Background task runner
     │
     ├─────────────────────────────────────────────────────┐
     │                                                     │
     ▼                                                     ▼
Neon (PostgreSQL)                                   Upstash (Redis)
  users, analyses,                                   API cache
  agent_outputs,                                     WebSocket pub/sub
  memos, documents
     │
     ▼
Claude API (Anthropic)        ChromaDB (Render volume)
  All 8 agent LLM calls         Vector embeddings for RAG
```

### Environment separation

| Variable               | Development                                                      | Production                 |
| ---------------------- | ---------------------------------------------------------------- | -------------------------- |
| `DATABASE_URL`         | Local Docker PostgreSQL                                          | Neon connection string     |
| `REDIS_URL`            | Local Docker Redis                                               | Upstash Redis URL          |
| `LANGCHAIN_PROJECT`    | `airp-dev`                                                       | `airp-prod`                |
| `LANGCHAIN_TRACING_V2` | `true` (enabled from Phase 7 onward — was `false` in Phases 1–6) | `true`                     |
| `ANTHROPIC_MODEL`      | `claude-haiku-4-20250514`                                        | `claude-sonnet-4-20250514` |
| `ENVIRONMENT`          | `development`                                                    | `production`               |

All environment variables are documented in `.env.example`.
Never commit `.env` to version control.

---

_Last updated: T-008 — Write initial documentation (Phase 0, Week 1)_
