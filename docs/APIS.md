# AIRP — External APIs & Services Reference

> **Canonical reference for every external service AIRP depends on.**
> Maintained as part of T-006 (Phase 0, Week 1).
> Update this file whenever a new service is added or a limit changes.

---

## Table of Contents

1. [AI / LLM](#1-ai--llm)
2. [Observability](#2-observability)
3. [Database](#3-database)
4. [Cache](#4-cache)
5. [Authentication](#5-authentication)
6. [Market Data APIs](#6-market-data-apis)
7. [Hosting & Deployment](#7-hosting--deployment)
8. [Local / No-Key Services](#8-local--no-key-services)
9. [Rate Limit Strategy](#9-rate-limit-strategy)
10. [Sign-Up Checklist](#10-sign-up-checklist)

---

## 1. AI / LLM

### Anthropic (Claude API)

| Field              | Detail                                                                 |
|--------------------|------------------------------------------------------------------------|
| **Purpose**        | LLM backbone for all 8 agents. Every agent prompt goes through Claude. |
| **Free Limit**     | Covered by existing Claude Pro subscription (usage-based, monitor closely) |
| **Sign-up URL**    | https://console.anthropic.com                                          |
| **API Key Format** | `sk-ant-api03-...`                                                     |
| **Env Variable**   | `ANTHROPIC_API_KEY`                                                    |
| **Model Variable** | `ANTHROPIC_MODEL` (default: `claude-sonnet-4-20250514`)                |
| **Dashboard**      | https://console.anthropic.com/settings/keys                           |
| **Docs**           | https://docs.anthropic.com                                             |
| **Notes**          | Monitor token usage via LangSmith. Use `claude-haiku-4-20250514` during development to reduce cost. Switch to Sonnet/Opus for demos. |

---

## 2. Observability

### LangSmith

| Field            | Detail                                                                         |
|------------------|--------------------------------------------------------------------------------|
| **Purpose**      | Traces every agent call — token usage, latency per node, prompt versions, evals |
| **Free Limit**   | 5,000 traces/month — more than sufficient for development and demo              |
| **Sign-up URL**  | https://smith.langchain.com                                                    |
| **API Key Format** | `ls__...`                                                                    |
| **Env Variable** | `LANGSMITH_API_KEY`                                                            |
| **Other Vars**   | `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_PROJECT=airp-dev`, `LANGCHAIN_ENDPOINT=https://api.smith.langchain.com` |
| **Dashboard**    | https://smith.langchain.com/settings                                           |
| **Docs**         | https://docs.smith.langchain.com                                               |
| **Notes**        | Set `LANGCHAIN_PROJECT` to a different name per environment (`airp-dev`, `airp-prod`). Traces are disabled if `LANGCHAIN_TRACING_V2=false` — useful when iterating quickly and not wanting to burn the free quota. |

---

## 3. Database

### Neon (PostgreSQL)

| Field            | Detail                                                                          |
|------------------|---------------------------------------------------------------------------------|
| **Purpose**      | Primary relational database — users, analyses, agent outputs, memos, job status |
| **Free Limit**   | 0.5 GB storage, 1 project, unlimited queries — sufficient for dev and demo      |
| **Sign-up URL**  | https://neon.tech                                                               |
| **Env Variable** | `DATABASE_URL`                                                                  |
| **URL Format**   | `postgresql+asyncpg://user:password@ep-xxx.neon.tech/airp?sslmode=require`     |
| **Dashboard**    | https://console.neon.tech                                                       |
| **Docs**         | https://neon.tech/docs                                                          |
| **Notes**        | After sign-up: create a project named `airp`. Go to **Connection Details** and copy the connection string. Select **asyncpg** driver (not psycopg2) — AIRP uses async SQLAlchemy. Enable connection pooling under the Neon dashboard for production use. |

---

## 4. Cache

### Upstash Redis

| Field            | Detail                                                                    |
|------------------|---------------------------------------------------------------------------|
| **Purpose**      | API response caching — protects free tier rate limits across all data APIs |
| **Free Limit**   | 10,000 commands/day, 256 MB storage                                       |
| **Sign-up URL**  | https://upstash.com                                                       |
| **Env Variables** | `REDIS_URL`, `REDIS_TOKEN`                                               |
| **URL Format**   | `rediss://default:password@host.upstash.io:6379`                         |
| **Dashboard**    | https://console.upstash.com                                               |
| **Docs**         | https://upstash.com/docs/redis/overall/getstarted                         |
| **Notes**        | After sign-up: create a database named `airp-cache`, select the region closest to your Render backend. Copy the **REST URL** and **REST Token** from the dashboard. The `REDIS_TOKEN` is only required when using Upstash cloud — local Docker Redis does not use it. |

**Cache TTLs (configured via env vars):**

| Variable                 | Default | Rationale                                   |
|--------------------------|---------|---------------------------------------------|
| `CACHE_TTL_STOCK`        | `900`   | 15 min — stock prices update frequently     |
| `CACHE_TTL_NEWS`         | `3600`  | 1 hour — news headlines are stable short-term |
| `CACHE_TTL_MACRO`        | `86400` | 24 hours — macro data changes rarely        |
| `CACHE_TTL_FUNDAMENTALS` | `3600`  | 1 hour — financial statements are stable    |

---

## 5. Authentication

### Clerk

| Field            | Detail                                                                      |
|------------------|-----------------------------------------------------------------------------|
| **Purpose**      | User authentication — sign-up, sign-in, session management, JWT verification |
| **Free Limit**   | 10,000 Monthly Active Users (MAU) — far more than needed for a portfolio project |
| **Sign-up URL**  | https://clerk.com                                                           |
| **Env Variables** | `CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`, `CLERK_JWT_ISSUER`           |
| **Key Formats**  | Secret: `sk_test_...` / `sk_live_...` · Publishable: `pk_test_...` / `pk_live_...` |
| **Dashboard**    | https://dashboard.clerk.com                                                 |
| **Docs**         | https://clerk.com/docs                                                      |
| **Notes**        | After sign-up: create an application named `airp`. Under **API Keys**, copy the Secret Key and Publishable Key. Under **JWT Templates**, note the issuer URL (format: `https://your-app.clerk.accounts.dev`) — this goes into `CLERK_JWT_ISSUER`. The publishable key is duplicated as `VITE_CLERK_PUBLISHABLE_KEY` for the React frontend (Vite only exposes `VITE_`-prefixed vars to the browser). |

---

## 6. Market Data APIs

### NewsAPI

| Field            | Detail                                                                      |
|------------------|-----------------------------------------------------------------------------|
| **Purpose**      | Company news headlines — last 30 days — used by the News Sentiment Agent    |
| **Free Limit**   | 100 requests/day on the Developer plan                                      |
| **Sign-up URL**  | https://newsapi.org/register                                                |
| **API Key Format** | 32-character hex string                                                   |
| **Env Variable** | `NEWS_API_KEY`                                                              |
| **Dashboard**    | https://newsapi.org/account                                                 |
| **Docs**         | https://newsapi.org/docs                                                    |
| **Key Endpoint** | `GET https://newsapi.org/v2/everything?q={company}&apiKey={key}`           |
| **Notes**        | Cache responses for 1 hour (`CACHE_TTL_NEWS=3600`). Free tier restricts results to articles older than 1 month in some queries — always test with a recent company name. |

---

### Alpha Vantage

| Field            | Detail                                                                    |
|------------------|---------------------------------------------------------------------------|
| **Purpose**      | Additional fundamentals and earnings data for the Fundamental Analyst Agent |
| **Free Limit**   | 25 requests/day on the free tier                                          |
| **Sign-up URL**  | https://www.alphavantage.co/support/#api-key                              |
| **API Key Format** | Alphanumeric string (e.g. `ABCDEF1234567890`)                           |
| **Env Variable** | `ALPHA_VANTAGE_KEY`                                                       |
| **Dashboard**    | https://www.alphavantage.co/support/#api-key                              |
| **Docs**         | https://www.alphavantage.co/documentation                                 |
| **Key Endpoints** | `INCOME_STATEMENT`, `BALANCE_SHEET`, `CASH_FLOW`, `EARNINGS`            |
| **Notes**        | Use very sparingly — only 25 req/day. Redis cache (`CACHE_TTL_FUNDAMENTALS=3600`) is essential. yFinance covers most fundamentals for free; Alpha Vantage is a supplementary source only. |

---

### yFinance

| Field            | Detail                                                                    |
|------------------|---------------------------------------------------------------------------|
| **Purpose**      | Stock prices, OHLCV, income statement, balance sheet, cash flow           |
| **Free Limit**   | Unlimited (unofficial Yahoo Finance scraper — no API key required)        |
| **Sign-up URL**  | Not required                                                              |
| **API Key**      | None — no key needed                                                      |
| **Env Variable** | None required                                                             |
| **Docs**         | https://pypi.org/project/yfinance                                         |
| **Notes**        | Use Redis cache (`CACHE_TTL_STOCK=900`) to avoid Yahoo rate limits. Install via `pip install yfinance`. Primary data source for price and fundamental data. |

---

### Screener.in (Web Scraping)

| Field            | Detail                                                                    |
|------------------|---------------------------------------------------------------------------|
| **Purpose**      | Indian stock peer comparison, PE/PB ratios, earnings call transcripts     |
| **Free Limit**   | Free — scraped directly from public pages                                 |
| **Sign-up URL**  | Not required (public data)                                                |
| **API Key**      | None                                                                      |
| **Env Variable** | `SCREENER_BASE_URL` (default: `https://www.screener.in`)                  |
| **Docs**         | https://www.screener.in/api                                               |
| **Notes**        | Scrape respectfully — add delays between requests. Cache aggressively. The base URL is a configurable variable in case Screener changes their site structure. |

---

### RBI Data (Web Scraping)

| Field            | Detail                                                                    |
|------------------|---------------------------------------------------------------------------|
| **Purpose**      | RBI monetary policy rates, inflation, macro indicators for the Macro Economist Agent |
| **Free Limit**   | Free — public government data                                             |
| **Sign-up URL**  | Not required                                                              |
| **API Key**      | None                                                                      |
| **Env Variable** | `RBI_BASE_URL` (default: `https://www.rbi.org.in`)                        |
| **Docs**         | https://www.rbi.org.in/Scripts/Statistics.aspx                           |
| **Notes**        | Cache for 24 hours (`CACHE_TTL_MACRO=86400`) — macro data changes rarely. |

---

## 7. Hosting & Deployment

### Vercel (Frontend)

| Field            | Detail                                                                    |
|------------------|---------------------------------------------------------------------------|
| **Purpose**      | React frontend hosting — auto-deploys from GitHub, preview URLs on every PR |
| **Free Limit**   | Unlimited hobby projects, 100 GB bandwidth/month, 100 deployments/day    |
| **Sign-up URL**  | https://vercel.com/signup                                                 |
| **Env Variables** | Set in Vercel dashboard under Project → Settings → Environment Variables |
| **Dashboard**    | https://vercel.com/dashboard                                              |
| **Docs**         | https://vercel.com/docs                                                   |
| **Notes**        | Connect your GitHub account during sign-up. Import the `airp` repo. Set root directory to `frontend/`. Add all `VITE_` environment variables in the Vercel dashboard — never commit them. Preview deployments are created automatically for every PR. |

---

### Render (Backend)

| Field            | Detail                                                                    |
|------------------|---------------------------------------------------------------------------|
| **Purpose**      | FastAPI backend hosting — auto-deploys from `main` branch                 |
| **Free Limit**   | 750 free hours/month (one web service runs free indefinitely on the free plan) |
| **Sign-up URL**  | https://render.com/register                                               |
| **Env Variables** | Set in Render dashboard under Service → Environment                      |
| **Dashboard**    | https://dashboard.render.com                                              |
| **Docs**         | https://render.com/docs                                                   |
| **Notes**        | Connect GitHub account. Create a **Web Service** pointing to the `airp` repo. Set root directory to `backend/`. The free plan spins down after 15 minutes of inactivity — expect a cold start delay. For demo purposes, this is acceptable. Set all backend environment variables in the Render dashboard. |

---

### GitHub Actions

| Field            | Detail                                                                    |
|------------------|---------------------------------------------------------------------------|
| **Purpose**      | CI/CD — runs lint (black, flake8, mypy) and pytest on every push          |
| **Free Limit**   | 2,000 CI minutes/month for public repositories (effectively unlimited for this project) |
| **Sign-up URL**  | https://github.com (account already required for the repo)               |
| **Env Variable** | `GITHUB_TOKEN` (auto-injected by GitHub Actions — no manual setup)        |
| **Docs**         | https://docs.github.com/en/actions                                        |
| **Notes**        | No separate sign-up needed — GitHub Actions is enabled automatically on all repos. The workflow file lives at `.github/workflows/ci.yml` (created in T-004). Secrets for CI (e.g. `ANTHROPIC_API_KEY` for integration tests) are added under Repo → Settings → Secrets → Actions. |

---

## 8. Local / No-Key Services

These services run entirely locally or have no API key requirement.

| Service                  | Purpose                                          | Install                          |
|--------------------------|--------------------------------------------------|----------------------------------|
| **ChromaDB**             | Vector database for RAG — stores news and earnings transcript embeddings | `pip install chromadb` or Docker |
| **sentence-transformers** | Local text embedding model — no API cost       | `pip install sentence-transformers` |
| **Docker + Compose**     | One-command local dev environment               | https://docs.docker.com/get-docker |

---

## 9. Rate Limit Strategy

AIRP's caching strategy is designed so that a full analysis run (8 agents) stays well within all free tier limits.

| Service       | Free Limit        | Calls Per Analysis (est.) | Daily Analyses Possible |
|---------------|-------------------|---------------------------|-------------------------|
| NewsAPI       | 100 req/day       | ~3 (cached 1h)            | ~33 analyses/day        |
| Alpha Vantage | 25 req/day        | ~2 (cached 1h)            | ~12 analyses/day        |
| yFinance      | Unlimited         | ~5 (cached 15min)         | Unlimited               |
| LangSmith     | 5,000 traces/month | ~20 traces per analysis  | ~250 analyses/month     |
| Anthropic     | Pro subscription  | ~8 LLM calls              | Monitor in LangSmith    |

**Redis is the primary rate limit shield.** Every external API call is checked against Redis before hitting the real endpoint. A cache hit costs 1 Redis command against the 10,000/day Upstash limit — negligible compared to the API savings.

---

## 10. Sign-Up Checklist

Use this checklist when setting up AIRP for the first time. Complete in order — some services depend on others being registered first.

### Required (all must be done before any code runs)

- [ ] **Anthropic** — https://console.anthropic.com → create API key → paste into `ANTHROPIC_API_KEY`
- [ ] **LangSmith** — https://smith.langchain.com → create API key → paste into `LANGSMITH_API_KEY`
- [ ] **Neon DB** — https://neon.tech → create project `airp` → copy connection string → paste into `DATABASE_URL`
- [ ] **Upstash Redis** — https://upstash.com → create database `airp-cache` → copy URL + Token → paste into `REDIS_URL` and `REDIS_TOKEN`
- [ ] **Clerk** — https://clerk.com → create application `airp` → copy Secret Key + Publishable Key → paste into `CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`, and `VITE_CLERK_PUBLISHABLE_KEY`; note JWT issuer URL → paste into `CLERK_JWT_ISSUER`
- [ ] **NewsAPI** — https://newsapi.org/register → copy API key → paste into `NEWS_API_KEY`
- [ ] **Alpha Vantage** — https://alphavantage.co/support/#api-key → copy API key → paste into `ALPHA_VANTAGE_KEY`

### Hosting (set up before final deployment in Phase 8)

- [ ] **Vercel** — https://vercel.com/signup → connect GitHub → import `airp` repo → set root to `frontend/` → add `VITE_` env vars
- [ ] **Render** — https://render.com/register → connect GitHub → create Web Service → set root to `backend/` → add all backend env vars

### After all keys are collected

- [ ] Copy `.env.example` to `.env`: `cp .env.example .env`
- [ ] Fill in every `replace-with-*` placeholder in `.env`
- [ ] Verify `.env` is in `.gitignore` (never commit this file)
- [ ] Run `docker-compose up` to start local services (PostgreSQL, Redis, ChromaDB)
- [ ] Run `pytest` to confirm the environment is correctly configured

---

*Last updated: T-006 — Register all free API accounts (Phase 0, Week 1)*
