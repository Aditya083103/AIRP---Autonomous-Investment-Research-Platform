# AIRP — Autonomous Investment Research Platform

[![CI](https://github.com/Aditya083103/AIRP---Autonomous-Investment-Research-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/Aditya083103/AIRP---Autonomous-Investment-Research-Platform/actions/workflows/ci.yml)
[![Verdict Accuracy](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fairp-backend.onrender.com%2Fapi%2Fv1%2Faccuracy%2Fsummary&query=%24.overall_accuracy_pct&suffix=%25&label=verdict%20accuracy&color=blue)](https://airp-autonomous-investment-research.vercel.app/accuracy)
![Python](https://img.shields.io/badge/python-3.11-blue)
![TypeScript](https://img.shields.io/badge/typescript-5.x-3178c6)
![License](https://img.shields.io/badge/license-MIT-green)

> A production-grade multi-agent AI system that simulates a hedge-fund investment
> committee — eight collaborating agents research, debate, and challenge each other,
> then produce a downloadable Investment Memo with a BUY / HOLD / SELL verdict and a
> conviction score. A conversational AIRP Assistant lets you explore any result afterward.

**🔗 Live app:** [airp-autonomous-investment-research.vercel.app](https://airp-autonomous-investment-research.vercel.app)
**🔗 Live API:** [airp-backend.onrender.com](https://airp-backend.onrender.com) · [API docs (Swagger)](https://airp-backend.onrender.com/docs)

> ⚠️ The API runs on Render's free tier and spins down after inactivity — the first
> request after an idle period can take ~50s to cold-start. Subsequent requests are fast.

<!-- DEMO GIF — replace with the recorded end-to-end flow (T-077):
     landing → "TCS vs Infosys" → live agents → debate viewer → memo PDF.
     ![AIRP demo](docs/assets/airp-demo.gif) -->

---

## Table of contents

- [What it does](#what-it-does)
- [Live demo](#live-demo)
- [The 8-agent investment committee](#the-8-agent-investment-committee)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Quick start (local, <15 min)](#quick-start-local-15-min)
- [Development setup (without Docker)](#development-setup-without-docker)
- [Running tests](#running-tests)
- [Deployment](#deployment)
- [Observability & evaluation](#observability--evaluation)
- [Project structure](#project-structure)
- [Documentation](#documentation)
- [Project status](#project-status)
- [License](#license)

---

## What it does

Ask _"Should I invest in TCS or Infosys?"_ and AIRP orchestrates eight collaborating
AI agents that research, debate, and challenge one another before arriving at a final
recommendation. It does not return a single LLM answer — it runs a structured analytical
workflow modelled on how a real investment committee operates: independent analysis,
group debate, a devil's-advocate challenge, and a final decision by a single accountable
authority.

The system produces a professional **Investment Memo** (downloadable PDF) containing an
executive summary, investment thesis, bull case, bear case, risk analysis, valuation, and
a final **BUY / HOLD / SELL** verdict with a **conviction score (1–10)** and price target.
The whole pipeline typically completes in **30–80 seconds**, and every agent's progress is
streamed live to the dashboard over WebSocket.

Once a memo exists, the **AIRP Assistant** — a floating chat widget on every page — lets
you ask follow-up questions about that memo, or about your entire analysis history, in
plain English. It explains the reasoning behind a verdict already reached; by design it
never issues, revises, or can be talked into issuing a new one.

### Key features

- **8-agent committee** with distinct personas, toolsets, and analytical mandates
- **Adversarial debate loop** — a dedicated Contrarian agent attacks every bullish thesis
- **Live pipeline streaming** — watch each agent activate in real time over WebSocket
- **Interactive live graph** — a ReactFlow view of the LangGraph state machine as it runs
- **DCF valuation** with sector-aware WACC calibration and peer comparison
- **RAG over uploaded documents** — drop in an annual report or earnings transcript to enrich analysis
- **Verdict accuracy tracker** — AIRP scores its own past verdicts against real market outcomes
- **Conversational assistant** — memo-scoped and portfolio-wide Q&A with strict guardrails
- **Full observability** — every agent call traced in LangSmith with token usage and latency
- **Investment Memo PDF export** — professional, formatted, downloadable

## Live demo

| Try it | Link |
| ------ | ---- |
| Web app | [airp-autonomous-investment-research.vercel.app](https://airp-autonomous-investment-research.vercel.app) |
| API root / health | [airp-backend.onrender.com/health](https://airp-backend.onrender.com/health) |
| Interactive API docs | [airp-backend.onrender.com/docs](https://airp-backend.onrender.com/docs) |
| Verdict accuracy dashboard | [/accuracy](https://airp-autonomous-investment-research.vercel.app/accuracy) |

<!-- DEMO VIDEO (T-077) — embed the 3-minute walkthrough here:
     [![Watch the demo](docs/assets/video-thumb.png)](https://youtu.be/YOUR_VIDEO_ID) -->

## The 8-agent investment committee

| # | Agent | Mandate | Key tools | Output |
| - | ----- | ------- | --------- | ------ |
| 1 | **Fundamental Analyst** | Revenue growth, margins, free cash flow, debt, balance-sheet health over 4 years | yFinance, Alpha Vantage | `FundamentalAnalysis` (score 1–10) |
| 2 | **Technical Analyst** | Price trends, 50d/200d MAs, RSI, momentum, 52-week positioning | yFinance OHLCV | `TechnicalAnalysis` (BUY/HOLD/SELL) |
| 3 | **News Sentiment Agent** | 30-day news sentiment, red-flag detection, RAG over articles | NewsAPI, ChromaDB | `SentimentAnalysis` (−1 to +1) |
| 4 | **Macro Economist** | RBI rates, inflation, GDP, sector tailwinds/headwinds for India | RBI / macro sources | `MacroAnalysis` |
| 5 | **Risk Officer** | Governance failures, fraud indicators, regulatory & concentration risk | All prior agent outputs | `RiskAnalysis` (score, flags[]) |
| 6 | **Contrarian Investor** | Its only job: disagree — dismantle every bull thesis and surface overlooked risk | Full debate state | `ContrarianReport` |
| 7 | **Valuation Agent** | DCF (sector-aware WACC), PE/PB/EV-EBITDA vs peers, upside/downside | Screener.in, yFinance | `ValuationOutput` |
| 8 | **Portfolio Manager** | Reads the full debate, weighs all evidence, issues the final memo & verdict | Full pipeline state | `InvestmentDecision` (+ memo) |

Each agent lives in [`backend/agents/`](backend/agents/); the provider behind every one is
abstracted by [`backend/agents/llm_factory.py`](backend/agents/llm_factory.py) via the
`LLM_PROVIDER` env var. See [docs/AGENTS.md](docs/AGENTS.md) for every persona, prompt, and
output schema.

## Architecture

AIRP is a five-layer full-stack application. A single typed `InvestmentState` object flows
through every LangGraph node and is persisted to PostgreSQL after each step, so a failed run
can resume mid-pipeline rather than restarting.

```
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 1 — Frontend   React 18 · TypeScript · Vite · Tailwind          │
│ Dashboard · analysis input · live agent progress · debate viewer ·    │
│ live graph · Investment Memo + PDF · AIRP Assistant chat widget       │
│                              ▲ HTTP / WebSocket                        │
├──────────────────────────────┼────────────────────────────────────────┤
│ LAYER 2 — Backend API  FastAPI · Python 3.11 · async                  │
│ REST (auth, analysis, results, accuracy, chat) · WebSocket streaming  │
│ · background task runner · document upload → ChromaDB                 │
│                              ▲ triggers pipeline                       │
├──────────────────────────────┼────────────────────────────────────────┤
│ LAYER 3 — Agent committee  LangGraph StateGraph · 8 agents            │
│ Planner → 4 research agents (parallel) → debate loop → Risk +         │
│ Valuation → Portfolio Manager → Investment Memo PDF                   │
├───────────────────────────────────────────────────────────────────────┤
│ LAYER 4 — Data & storage  PostgreSQL (Neon) · ChromaDB · Redis        │
│ (Upstash) · yFinance · NewsAPI · Alpha Vantage · Screener.in · RBI    │
├───────────────────────────────────────────────────────────────────────┤
│ LAYER 5 — Observability & DevOps  LangSmith · GitHub Actions CI/CD ·  │
│ Docker · Vercel (frontend) · Render (backend)                         │
└───────────────────────────────────────────────────────────────────────┘
```

Full detail — request flow, state design, and every design decision — is in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); the auto-exported LangGraph diagram is in
[docs/GRAPH_DIAGRAM.md](docs/GRAPH_DIAGRAM.md).

## Tech stack

| Layer         | Technologies                                                          |
| ------------- | --------------------------------------------------------------------- |
| Frontend      | React 18 · TypeScript · Vite · Tailwind CSS · React Query · Recharts · ReactFlow |
| Backend       | FastAPI · Python 3.11 · WebSocket · Pydantic v2 · SQLAlchemy (async) · Alembic |
| Agents        | LangGraph · LangChain · Groq (Llama 3.3 70B, dev) · Claude API (demo)  |
| Storage       | PostgreSQL (Neon) · ChromaDB (RAG) · Redis (Upstash)                   |
| PDF           | WeasyPrint                                                             |
| Observability | LangSmith · GitHub Actions CI/CD                                       |
| Deployment    | Vercel (frontend) · Render (backend) · Docker + docker-compose (local) |

[`backend/agents/llm_factory.py`](backend/agents/llm_factory.py) abstracts the LLM provider
behind one `LLM_PROVIDER` env var — every agent and the AIRP Assistant run on Groq's free
tier throughout development and switch to Claude for the polished demo.

## Quick start (local, <15 min)

```bash
# 1. Clone
git clone https://github.com/Aditya083103/AIRP---Autonomous-Investment-Research-Platform.git
cd AIRP---Autonomous-Investment-Research-Platform

# 2. Configure environment
cp .env.example .env
# Fill in your API keys in .env — see docs/APIS.md for every service and its free tier

# 3. Start the whole stack with Docker
docker-compose up
# Frontend  → http://localhost:3000
# API       → http://localhost:8000
# API docs  → http://localhost:8000/docs
# Postgres  → localhost:5432 (airp/airp)
# Redis     → localhost:6379
# ChromaDB  → http://localhost:8001
```

`docker-compose up` builds and starts five containers — `api`
([`backend/Dockerfile`](backend/Dockerfile)), `frontend`
([`frontend/Dockerfile.dev`](frontend/Dockerfile.dev)), `postgres`, `redis`, and `chromadb`
— runs Alembic migrations automatically before the API serves traffic (see
[`backend/docker-entrypoint.sh`](backend/docker-entrypoint.sh)), and bind-mounts both
`backend/` and `frontend/` source so host edits hot-reload inside the containers. See
[`docker-compose.yml`](docker-compose.yml) for the full breakdown. A separate
production-style frontend image ([`frontend/Dockerfile`](frontend/Dockerfile), multi-stage
build served by nginx) exists for containerized deploys outside Vercel.

## Development setup (without Docker)

```bash
# Backend
python -m venv .venv
.venv\Scripts\activate         # Windows
# source .venv/bin/activate    # macOS / Linux
pip install -r backend/requirements-dev.txt
pip install -r backend/requirements.txt
pre-commit install

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

## Running tests

```bash
# Backend — set the required environment variable first
export ENVIRONMENT=test         # macOS / Linux
# $env:ENVIRONMENT="test"       # Windows PowerShell (Git Bash: set ENVIRONMENT=test on its own line)

pytest                          # unit tests (fast, mocked)
pytest -m integration           # real API calls (needs .env)
pytest --cov --cov-report=html  # coverage report
```

```bash
# Frontend
cd frontend
npm run test:run    # full Vitest suite, once
npm run lint        # ESLint, --max-warnings 0
npm run type-check  # tsc --noEmit (strict mode)
npm run build       # production build
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the full backend gate
(black, isort, flake8, mypy, bandit, pytest+coverage), the full frontend gate (type-check,
lint, prettier, Vitest, build), and a Docker image build for both services on every push
and PR. A single `ci-pass` job gates branch protection.

## Deployment

| Component | Platform | Config |
| --------- | -------- | ------ |
| Frontend  | Vercel   | [`frontend/vercel.json`](frontend/vercel.json) · Root Directory `frontend` · SPA rewrites · asset caching + security headers |
| Backend   | Render   | [`render.yaml`](render.yaml) Blueprint · Docker runtime · `/health` check · auto-deploy from `main` |

**Frontend env vars** (set in Vercel → Settings → Environment Variables, for Production and
Preview):

```
VITE_API_BASE_URL=https://airp-backend.onrender.com/api/v1
VITE_AUTH_BASE_URL=https://airp-backend.onrender.com/auth
VITE_WS_BASE_URL=wss://airp-backend.onrender.com
```

**Backend env vars** live on Render (every secret is `sync: false` in `render.yaml` and
entered in the dashboard). Note `CORS_ORIGINS` must list the exact Vercel origin(s) — the
backend runs CORS with `allow_credentials=True`, so a wildcard `*` is invalid. Every
variable is cross-checked field-by-field against `backend/config.py`; see
[docs/week-28/T-074-PRE-DEPLOY-AUDIT.md](docs/week-28/T-074-PRE-DEPLOY-AUDIT.md) and
[docs/week-28/T-075-deploy-vercel.md](docs/week-28/T-075-deploy-vercel.md) for the full
deploy walkthroughs.

## Observability & evaluation

AIRP has **two complementary evaluation systems**:

- **Verdict accuracy tracker** (Phase 8) — records every BUY/HOLD/SELL verdict, then scores
  it against real market movement over a horizon-appropriate window using a dead-zone
  directional rule. Exposed at `GET /api/v1/accuracy/summary` and on the `/accuracy`
  dashboard. Methodology, horizon mapping, and worked examples in
  [docs/EVALUATION.md](docs/EVALUATION.md).
- **LangSmith agent-quality eval suite** (Phase 11) — offline evals for Fundamental Analyst
  accuracy, sentiment direction, debate quality, and end-to-end latency benchmarking, plus
  the framework design. See [docs/AGENT_EVALUATION.md](docs/AGENT_EVALUATION.md) and
  [docs/EVAL_FRAMEWORK_DESIGN.md](docs/EVAL_FRAMEWORK_DESIGN.md).

Every agent call, tool use, token count, and per-node latency is traced in LangSmith. Live
per-node latency profiling is documented in
[docs/PERFORMANCE_PROFILE.md](docs/PERFORMANCE_PROFILE.md).

<!-- LANGSMITH SCREENSHOT (T-076 acceptance criterion) — add a trace-dashboard image:
     ![LangSmith trace](docs/assets/langsmith-trace.png) -->

## Project structure

```
airp/
├── backend/
│   ├── agents/       # 8 agent definitions + llm_factory + tracing
│   ├── graph/        # LangGraph StateGraph + routing + state persistence
│   ├── routers/      # FastAPI handlers (auth, analysis, results, accuracy, chat, health)
│   ├── models/       # SQLAlchemy ORM + Pydantic schemas
│   ├── services/     # Business logic (analysis, accuracy_tracker, chat_llm, chat_service)
│   ├── tools/        # LangChain tool definitions
│   ├── db/           # PostgreSQL, ChromaDB, Redis clients
│   ├── migrations/   # Alembic migrations
│   ├── tests/        # pytest unit + integration tests
│   ├── Dockerfile           # production backend image
│   └── docker-entrypoint.sh # runs `alembic upgrade head`, then execs uvicorn
├── frontend/
│   ├── src/
│   │   ├── components/   # design system + chat/ (AIRP Assistant), graph/, results/, charts/
│   │   ├── pages/
│   │   ├── hooks/        # useAnalysisStream, useChatWidget, useChatStream, useAuth
│   │   ├── api/ · config/ · lib/ · types/
│   ├── Dockerfile        # production image (multi-stage → nginx)
│   ├── Dockerfile.dev    # local dev image (Vite dev server, used by compose)
│   ├── vercel.json       # Vercel deploy config
│   └── nginx.conf.template
├── docs/             # Architecture, agents, data layer, evaluation, chat
├── docs/week-NN/     # Per-task workflow docs (branch → commit → PR)
├── .github/workflows/  # CI + scheduled verdict-accuracy evaluation
├── docker-compose.yml
├── render.yaml       # Render Blueprint (backend)
├── .env.example
└── README.md
```

## Documentation

| Doc | Contents |
| --- | -------- |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full system architecture — layers, request flow, state design, decisions |
| [AGENTS.md](docs/AGENTS.md) | Each agent's persona, tools, output schema, example output |
| [DATA_LAYER.md](docs/DATA_LAYER.md) | Data tools, caching strategy, per-source rate-limit handling |
| [STATE.md](docs/STATE.md) | `InvestmentState` shape, persistence, resumption design |
| [GRAPH_DIAGRAM.md](docs/GRAPH_DIAGRAM.md) | Auto-exported LangGraph state diagram |
| [EVALUATION.md](docs/EVALUATION.md) | Verdict accuracy methodology — horizons, dead-zone scoring, worked examples |
| [AGENT_EVALUATION.md](docs/AGENT_EVALUATION.md) | LangSmith agent-quality eval suite |
| [EVAL_FRAMEWORK_DESIGN.md](docs/EVAL_FRAMEWORK_DESIGN.md) | Evaluation framework design and rationale |
| [PERFORMANCE_PROFILE.md](docs/PERFORMANCE_PROFILE.md) | Per-agent and per-node latency profiling |
| [CHAT.md](docs/CHAT.md) | AIRP Assistant architecture, guardrails, personalization, transcripts |
| [APIS.md](docs/APIS.md) | External APIs, free-tier limits, env var names, rate-limit strategy |
| [CONTRIBUTING.md](docs/CONTRIBUTING.md) | Local setup, branch strategy, commit format, PR process |
| [CODING_STANDARDS.md](docs/CODING_STANDARDS.md) | Naming conventions, linting, pre-commit, CI checks |

## Project status

**✅ Complete.** 12 phases, ~107 tasks (`T-001`–`T-107`), built solo end-to-end and deployed
live on Vercel + Render at zero infrastructure cost.

| Phase | Name | Status |
| ----- | ---- | ------ |
| 0  | Project Setup & Standards        | ✅ Complete |
| 1  | Data Layer & APIs                | ✅ Complete |
| 2  | Research Agents                  | ✅ Complete |
| 3  | LangGraph Orchestration          | ✅ Complete |
| 4  | Debate Engine & Advanced Agents  | ✅ Complete |
| 5  | FastAPI Backend                  | ✅ Complete |
| 6  | React Frontend                   | ✅ Complete |
| 7  | Bug Fixes & Verdict Calibration  | ✅ Complete |
| 8  | Verdict Accuracy Tracker         | ✅ Complete |
| 9  | Live Graph Visualization         | ✅ Complete |
| 10 | AIRP Assistant (Chatbot)         | ✅ Complete |
| 11 | Evaluation Framework             | ✅ Complete |
| 12 | Polish, Deploy & Launch          | ✅ Complete |

## License

Released under the [MIT License](LICENSE).

---

_Built as a portfolio project to demonstrate production-level Agentic AI engineering —
multi-agent orchestration, adversarial debate, RAG, real-time streaming, full-stack delivery,
observability, and CI/CD. Total infrastructure cost: ₹0 — 100% free-tier stack._