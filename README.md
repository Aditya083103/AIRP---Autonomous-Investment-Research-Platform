# AIRP — Autonomous Investment Research Platform

[![CI](https://github.com/Aditya083103/AIRP---Autonomous-Investment-Research-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/Aditya083103/AIRP---Autonomous-Investment-Research-Platform/actions/workflows/ci.yml)
[![Verdict Accuracy](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fairp-api.onrender.com%2Fapi%2Fv1%2Faccuracy%2Fsummary&query=%24.overall_accuracy_pct&suffix=%25&label=verdict%20accuracy&color=blue)](https://airp.vercel.app/accuracy)

<!-- The accuracy badge and its link point at the eventual production URLs
     (airp-api.onrender.com / airp.vercel.app, per .env.example). They start
     resolving live once Phase 12 deploys the backend and frontend -- until
     then the badge renders "invalid" (no data at that URL yet), which is
     expected. See docs/EVALUATION.md for the full scoring methodology. -->

> A production-grade multi-agent AI system that simulates an investment committee,
> performing autonomous financial analysis and generating professional Investment Memos —
> with a conversational AIRP Assistant to explore the results afterward.

<!-- Demo GIF will go here after Phase 12 launch -->

## What it does

Ask _"Should I invest in TCS or Infosys?"_ and AIRP orchestrates 8 collaborating AI agents
that research, debate, and challenge each other — then produces a downloadable Investment Memo
with a BUY / HOLD / SELL verdict and conviction score. The full pipeline completes in under 90
seconds, with every agent's progress streamed live to the dashboard.

Once a memo exists, the **AIRP Assistant** — a floating chat widget available on every page —
lets you ask follow-up questions about it (or about your whole analysis history) in plain
English. It explains the reasoning behind a verdict already reached; it never issues, revises,
or is talked into issuing a new one.

## Tech stack

| Layer         | Technologies                                                        |
| ------------- | -------------------------------------------------------------------- |
| Frontend      | React 18 · TypeScript · Vite · Tailwind CSS · Recharts · ReactFlow  |
| Backend       | FastAPI · Python 3.11 · WebSocket · Pydantic v2 · SQLAlchemy async  |
| Agents        | LangGraph · LangChain · Groq (Llama 3.3 70B, dev) · Claude API (demo) |
| Storage       | PostgreSQL (Neon) · ChromaDB · Redis (Upstash)                      |
| Observability | LangSmith (Phase 11 evaluation gate) · GitHub Actions CI/CD          |
| Deployment    | Vercel (frontend) · Render (backend)                                 |

`backend/services/llm_factory.py` abstracts the LLM provider behind one `LLM_PROVIDER` env
var — every agent and the AIRP Assistant run on Groq's free tier through the full 25-week build,
and switch to Claude only for the polished demo (Phase 12).

## Quick start (local)

```bash
# 1. Clone
git clone https://github.com/Aditya083103/AIRP---Autonomous-Investment-Research-Platform.git
cd AIRP---Autonomous-Investment-Research-Platform

# 2. Configure environment
cp .env.example .env
# Fill in your API keys in .env — see docs/APIS.md for every service

# 3. Start everything with Docker
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
([`frontend/Dockerfile.dev`](frontend/Dockerfile.dev)), `postgres`,
`redis`, and `chromadb` — runs Alembic migrations automatically before
the API starts serving (see
[`backend/docker-entrypoint.sh`](backend/docker-entrypoint.sh)), and
bind-mounts both `backend/` and `frontend/` source so edits on the host
hot-reload inside the containers. See
[`docker-compose.yml`](docker-compose.yml) for the full service
breakdown. A separate production-style image
([`frontend/Dockerfile`](frontend/Dockerfile), multi-stage build served
by nginx) exists for containerized frontend deploys outside Vercel.

## Development setup (without Docker)

```bash
# Backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
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
# Backend — set required environment variable first
export ENVIRONMENT=test       # macOS / Linux
# $env:ENVIRONMENT="test"     # Windows PowerShell (Git Bash: set ENVIRONMENT=test, its own line)

pytest                          # unit tests only (fast, mocked)
pytest -m integration           # real API calls (needs .env)
pytest --cov --cov-report=html  # with coverage report
```

```bash
# Frontend
cd frontend
npm run test:run    # full Vitest suite, once
npm run lint         # ESLint, --max-warnings 0
npm run type-check   # tsc --noEmit (strict mode)
```

## Project structure

```
airp/
├── backend/
│   ├── agents/       # 8 agent definitions
│   ├── graph/        # LangGraph StateGraph + routing
│   ├── routers/      # FastAPI route handlers (incl. chat + chat_stream)
│   ├── models/       # SQLAlchemy ORM + Pydantic schemas
│   ├── services/     # Business logic layer (incl. chat_llm, chat_service)
│   ├── tools/        # LangChain tool definitions
│   ├── db/           # PostgreSQL, ChromaDB, Redis clients
│   ├── migrations/   # Alembic migrations
│   ├── tests/        # pytest unit + integration tests
│   ├── Dockerfile           # production backend image
│   └── docker-entrypoint.sh # runs `alembic upgrade head`, then execs CMD
├── frontend/
│   ├── src/
│   │   ├── components/   # incl. chat/ (AIRP Assistant widget)
│   │   ├── pages/
│   │   ├── hooks/        # incl. useChatWidget, useChatStream
│   │   ├── api/
│   │   ├── lib/
│   │   └── types/
│   ├── Dockerfile        # production image (multi-stage build → nginx)
│   ├── Dockerfile.dev    # local dev image (Vite dev server, used by compose)
│   └── nginx.conf.template
├── docs/             # Architecture, agents, data layer, chat docs
├── docs/week-NN/     # Per-task workflow docs (branch → commit → PR)
├── docker-compose.yml  # local dev: api + postgres + redis + chromadb + frontend
├── .env.example
└── README.md
```

## Documentation

| Doc                                                 | Contents                                                                             |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------- |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md)             | Full system architecture — layers, request flow, state design, design decisions       |
| [CONTRIBUTING.md](docs/CONTRIBUTING.md)             | Local setup, branch strategy, commit format, PR process, testing guide                |
| [CODING_STANDARDS.md](docs/CODING_STANDARDS.md)     | Naming conventions, linting rules, pre-commit setup, CI checks                        |
| [AGENTS.md](docs/AGENTS.md)                         | Each agent's persona, tools, output schema, example output                            |
| [APIS.md](docs/APIS.md)                             | External APIs, free tier limits, env variable names, rate limit strategy              |
| [DATA_LAYER.md](docs/DATA_LAYER.md)                 | Data tools, caching strategy, rate-limit handling per source                          |
| [STATE.md](docs/STATE.md)                           | `InvestmentState` shape, persistence, and resumption design                           |
| [GRAPH_DIAGRAM.md](docs/GRAPH_DIAGRAM.md)           | Auto-exported LangGraph state diagram                                                 |
| [PERFORMANCE_PROFILE.md](docs/PERFORMANCE_PROFILE.md) | Per-agent and per-node latency profiling                                            |
| [EVALUATION.md](docs/EVALUATION.md)                 | Verdict accuracy methodology — evaluation horizons, dead-zone scoring, worked examples |
| [CHAT.md](docs/CHAT.md)                             | AIRP Assistant architecture, guardrails, personalization, and example transcripts     |

## Status

12 phases, ~107 tasks (`T-001`–`T-107`, plus deferred evaluation/deploy tasks `T-067`–`T-080`
reordered into Phases 11–12). Phase 10 (AIRP Assistant) is now complete; next up is
**Phase 11 — Evaluation Framework**.

| Phase | Name                                | Status            |
| ----- | ------------------------------------ | ------------------ |
| 0     | Project Setup & Standards           | ✅ Complete        |
| 1     | Data Layer & APIs                   | ✅ Complete        |
| 2     | Research Agents                     | ✅ Complete        |
| 3     | LangGraph Orchestration             | ✅ Complete        |
| 4     | Debate Engine & Advanced Agents     | ✅ Complete        |
| 5     | FastAPI Backend                     | ✅ Complete        |
| 6     | React Frontend                      | ✅ Complete        |
| 7     | Bug Fixes & Verdict Calibration     | ✅ Complete        |
| 8     | Verdict Accuracy Tracker            | ✅ Complete        |
| 9     | Live Graph Visualization            | ✅ Complete        |
| 10    | AIRP Assistant (Chatbot)            | ✅ Complete         |
| 11    | Evaluation Framework                | ⬜ Not started      |
| 12    | Polish, Deploy & Launch             | ⬜ Not started      |

**Phase 10 detail:**

| Task  | Title                                    | Status |
| ----- | ------------------------------------------ | ------ |
| T-099 | `chat_sessions` / `chat_messages` schema   | ✅ Done |
| T-100 | Memo-scoped context builder                | ✅ Done |
| T-101 | Portfolio-wide tool-calling layer          | ✅ Done |
| T-102 | `chat_llm.py` + guardrail system prompt    | ✅ Done |
| T-103 | REST endpoints for chat sessions           | ✅ Done |
| T-104 | WebSocket token streaming                  | ✅ Done |
| T-105 | `ChatWidget.tsx` frontend                  | ✅ Done |
| T-106 | Personalization via `user_preferences`     | ✅ Done |
| T-107 | Tests + docs for AIRP Assistant            | ✅ Done |

---

_Built as a portfolio project to demonstrate production-level Agentic AI engineering.
Total infrastructure cost: ₹0 — 100% free-tier stack._