# AIRP — Autonomous Investment Research Platform

[![CI](https://github.com/Aditya083103/AIRP---Autonomous-Investment-Research-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/Aditya083103/AIRP---Autonomous-Investment-Research-Platform/actions/workflows/ci.yml)

> A production-grade multi-agent AI system that simulates an investment committee,
> performing autonomous financial analysis and generating professional Investment Memos.

<!-- Demo GIF will go here after Phase 8 -->

## What it does

Ask *"Should I invest in TCS or Infosys?"* and AIRP orchestrates 8 collaborating AI agents
that research, debate, and challenge each other — then produces a downloadable Investment Memo
with a BUY / HOLD / SELL verdict and conviction score. The full pipeline completes in under 90 seconds.

## Tech stack

| Layer | Technologies |
|-------|-------------|
| Frontend | React 18 · TypeScript · Vite · Tailwind CSS · Recharts |
| Backend | FastAPI · Python 3.11 · WebSocket · Pydantic v2 |
| Agents | LangGraph · LangChain · Claude API (Anthropic) |
| Storage | PostgreSQL (Neon) · ChromaDB · Redis (Upstash) |
| Observability | LangSmith · GitHub Actions CI/CD |
| Deployment | Vercel (frontend) · Render (backend) |

## Quick start (local)

```bash
# 1. Clone
git clone https://github.com/<your-handle>/airp.git
cd airp

# 2. Configure environment
cp .env.example .env
# Fill in your API keys in .env — see docs/APIS.md for every service

# 3. Start everything with Docker
docker-compose up
# API → http://localhost:8000
# Frontend → http://localhost:5173
# API docs → http://localhost:8000/docs
```

## Development setup (without Docker)

```bash
# Backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -r backend/requirements-dev.txt
pre-commit install

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

## Running tests

```bash
# Set required environment variable first
export ENVIRONMENT=test       # macOS / Linux
# $env:ENVIRONMENT="test"     # Windows PowerShell

pytest                          # unit tests only (fast, mocked)
pytest -m integration           # real API calls (needs .env)
pytest --cov --cov-report=html  # with coverage report
```

## Project structure

```
airp/
├── backend/
│   ├── agents/       # 8 agent definitions
│   ├── graph/        # LangGraph StateGraph + routing
│   ├── routers/      # FastAPI route handlers
│   ├── models/       # SQLAlchemy ORM + Pydantic schemas
│   ├── services/     # Business logic layer
│   ├── tools/        # LangChain tool definitions
│   ├── db/           # PostgreSQL, ChromaDB, Redis clients
│   └── tests/        # pytest unit + integration tests
├── frontend/
│   └── src/
│       ├── components/
│       ├── pages/
│       ├── hooks/
│       ├── api/
│       └── types/
├── docs/             # Architecture, agents, data layer docs
├── docker-compose.yml
├── .env.example
└── README.md
```

## Documentation

| Doc | Contents |
|-----|----------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full system architecture — layers, request flow, state design, design decisions |
| [CONTRIBUTING.md](docs/CONTRIBUTING.md) | Local setup, branch strategy, commit format, PR process, testing guide |
| [CODING_STANDARDS.md](docs/CODING_STANDARDS.md) | Naming conventions, linting rules, pre-commit setup, CI checks |
| [AGENTS.md](docs/AGENTS.md) | Each agent's persona, tools, output schema, example output |
| [APIS.md](docs/APIS.md) | External APIs, free tier limits, env variable names, rate limit strategy |

## Status

| Phase | Name | Status |
|-------|------|--------|
| 0 | Project Setup & Standards | ✅ Complete |
| 1 | Data Layer & APIs | ⬜ Not started |
| 2 | Research Agents | ⬜ Not started |
| 3 | LangGraph Orchestration | ⬜ Not started |
| 4 | Debate Engine & Advanced Agents | ⬜ Not started |
| 5 | FastAPI Backend | ⬜ Not started |
| 6 | React Frontend | ⬜ Not started |
| 7 | Evaluation Framework | ⬜ Not started |
| 8 | Polish, Deploy & Launch | ⬜ Not started |

---

*Built as a portfolio project to demonstrate production-level Agentic AI engineering.
Total infrastructure cost: ₹0 — 100% free-tier stack.*
