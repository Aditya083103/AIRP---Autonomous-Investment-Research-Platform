# T-006 — Register All Free API Accounts

| Field          | Detail                              |
|----------------|-------------------------------------|
| **Task ID**    | T-006                               |
| **Phase**      | 0 — Project Setup & Standards       |
| **Week**       | 1                                   |
| **Branch**     | `setup/api-keys`                    |
| **Status**     | ✅ Completed                        |
| **Merged into**| `main`                              |

---

## Objective

Register every external service AIRP depends on, collect all API keys and
connection strings, and document them in `docs/APIS.md` — the canonical
reference for every service, its free tier limit, its env variable name,
sign-up URL, and usage notes. At the end of this task, any engineer can
clone the repo, read `APIS.md`, and know exactly where to get every secret.

---

## Acceptance Criteria

| Criteria                                                              | Status |
|-----------------------------------------------------------------------|--------|
| `docs/APIS.md` lists every service used by AIRP                      | ✅     |
| Every entry includes: purpose, free limit, sign-up URL, env var name | ✅     |
| Rate limit strategy section explains how Redis protects free tiers   | ✅     |
| Sign-up checklist in `APIS.md` covers every required service         | ✅     |
| All env variable names match `.env.example` exactly                  | ✅     |
| No real API keys committed anywhere in the repo                      | ✅     |
| Task doc (`T-006-register-api-accounts.md`) created in `docs/week-01/` | ✅  |
| PR merged via squash and merge                                        | ✅     |

---

## Services Registered

| Service          | Purpose                          | Free Limit              | Env Variable(s)                                        |
|------------------|----------------------------------|-------------------------|--------------------------------------------------------|
| Anthropic        | LLM backbone (all 8 agents)      | Claude Pro subscription | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`                 |
| LangSmith        | Agent tracing + evals            | 5,000 traces/month      | `LANGSMITH_API_KEY`, `LANGCHAIN_TRACING_V2`, `LANGCHAIN_PROJECT` |
| Neon DB          | PostgreSQL (users, analyses)     | 0.5 GB storage          | `DATABASE_URL`, `DATABASE_TEST_URL`                    |
| Upstash Redis    | API response caching             | 10,000 commands/day     | `REDIS_URL`, `REDIS_TOKEN`                             |
| Clerk            | User authentication              | 10,000 MAU              | `CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`, `CLERK_JWT_ISSUER` |
| NewsAPI          | Company news (Sentiment Agent)   | 100 req/day             | `NEWS_API_KEY`                                         |
| Alpha Vantage    | Fundamentals + earnings data     | 25 req/day              | `ALPHA_VANTAGE_KEY`                                    |
| Vercel           | React frontend hosting           | Unlimited hobby         | Set in dashboard                                       |
| Render           | FastAPI backend hosting          | 750 hours/month         | Set in dashboard                                       |
| yFinance         | Stock prices + OHLCV             | Unlimited (no key)      | None required                                          |
| Screener.in      | Indian stock peer ratios         | Free (scraping)         | `SCREENER_BASE_URL`                                    |
| RBI              | Macro data                       | Free (scraping)         | `RBI_BASE_URL`                                         |

---

## Files Created / Modified

| File                                         | Action   | Purpose                                         |
|----------------------------------------------|----------|-------------------------------------------------|
| `docs/APIS.md`                               | Created  | Canonical reference for all external services   |
| `docs/week-01/T-006-register-api-accounts.md`| Created  | This task document                              |

---

## Complete Git Flow

### Step 1 — Ensure main is up to date

```bash
git checkout main
git pull origin main
```

Confirm you are on `main` and it is clean:

```bash
git status
# Expected: nothing to commit, working tree clean
git log --oneline -5
# Expected: T-005 squash commit at the top
```

---

### Step 2 — Create and checkout the feature branch

```bash
git checkout -b setup/api-keys
```

Verify you are on the new branch:

```bash
git branch
# Expected: * setup/api-keys
```

---

### Step 3 — Create the APIS.md file

Create the file at the correct path:

```bash
touch docs/APIS.md
```

Open `docs/APIS.md` in your editor and paste the complete content from the
`APIS.md` file delivered with this task. The file covers 10 sections:

1. AI / LLM (Anthropic)
2. Observability (LangSmith)
3. Database (Neon PostgreSQL)
4. Cache (Upstash Redis)
5. Authentication (Clerk)
6. Market Data APIs (NewsAPI, Alpha Vantage, yFinance, Screener.in, RBI)
7. Hosting & Deployment (Vercel, Render, GitHub Actions)
8. Local / No-Key Services (ChromaDB, sentence-transformers, Docker)
9. Rate Limit Strategy (table of calls per analysis vs daily limits)
10. Sign-Up Checklist (ordered steps to collect every key)

---

### Step 4 — Create this task document

```bash
touch docs/week-01/T-006-register-api-accounts.md
```

Paste the content of this file into it.

---

### Step 5 — Verify no real keys are present

Before staging anything, confirm you have not accidentally pasted a real
API key into any file:

```bash
# Check for common key patterns
grep -rn "sk-ant-api03-" docs/
grep -rn "ls__" docs/
grep -rn "newsapi" docs/ | grep -v "newsapi.org"
```

All results should be zero matches or only documentation URLs — never real
key values. Real keys belong only in your local `.env`, which is gitignored.

---

### Step 6 — Stage and commit

```bash
git add docs/APIS.md docs/week-01/T-006-register-api-accounts.md
git status
```

Expected output:

```
On branch setup/api-keys
Changes to be staged:
  new file: docs/APIS.md
  new file: docs/week-01/T-006-register-api-accounts.md
```

Commit with the correct format:

```bash
git commit -m "docs(apis): add APIS.md with all services, limits, and sign-up checklist"
```

---

### Step 7 — Push the branch

```bash
git push -u origin setup/api-keys
```

Expected output includes:

```
Branch 'setup/api-keys' set up to track remote branch 'setup/api-keys' from 'origin'.
```

---

### Step 8 — Create the Pull Request

Go to GitHub → your `airp` repository → you will see a banner:

> **setup/api-keys had recent pushes** → **Compare & pull request**

Click **Compare & pull request**.

---

## Pull Request

### Title

```
docs(apis): register all free API accounts and document in APIS.md
```

### Description

```markdown
## Summary

Registers every external service AIRP depends on and documents them in
`docs/APIS.md` — the canonical reference for all services, free tier limits,
env variable names, sign-up URLs, and usage notes. Also adds a rate limit
strategy section and an ordered sign-up checklist for onboarding any engineer.

## Changes

- `docs/APIS.md` created — 10 sections covering all 12 services AIRP uses
- Documents purpose, free limit, sign-up URL, env variable name, and usage
  notes for every service
- Rate limit strategy table shows calls per analysis vs daily free limits
- Sign-up checklist provides an ordered, actionable steps to collect every key
- All env variable names match `.env.example` exactly (validated manually)
- `docs/week-01/T-006-register-api-accounts.md` created — full task log

## Testing

- Manually verified all env variable names in `APIS.md` against `.env.example`
- Grep confirmed no real API keys are present in any committed file
- CI passes (lint only — no Python code changed in this PR)

## LangSmith Trace

Not applicable — this PR contains documentation only, no agent code changes.

## Screenshots

Not applicable — documentation PR.

## Related Issues

Closes #6
```

---

### Step 9 — Merge the PR

1. Confirm all CI checks pass (GitHub Actions runs on every PR)
2. Select **Squash and merge** from the merge dropdown
3. Edit the squash commit message to:

```
docs(apis): register all free API accounts and document in APIS.md (#6)
```

4. Click **Confirm squash and merge**
5. Click **Delete branch** to keep the remote clean

---

### Step 10 — Sync local main

```bash
git checkout main
git pull origin main
git branch -d setup/api-keys
```

Verify the squash commit is at the top:

```bash
git log --oneline -5
```

Expected:

```
a1b2c3d docs(apis): register all free API accounts and document in APIS.md (#6)
... (T-005 commit below)
```

---

## Problems Encountered & Solutions

### 1. Clerk JWT Issuer URL is not obvious from the dashboard

**Problem:** The `CLERK_JWT_ISSUER` variable requires a URL in the format
`https://your-app.clerk.accounts.dev`, but the Clerk dashboard does not label
this field clearly. New users often miss it.

**Solution:** Documented the exact navigation path in `APIS.md`:
Dashboard → your app → API Keys → JWT Templates. The issuer URL is shown
under the JWT template configuration. Added the format example
(`https://your-app.clerk.accounts.dev`) to make it unambiguous.

### 2. Neon connection string driver must be asyncpg, not psycopg2

**Problem:** Neon's default connection string uses `postgresql://` which maps
to psycopg2. AIRP uses async SQLAlchemy which requires the `asyncpg` driver.
Using the wrong driver causes a runtime error in FastAPI.

**Solution:** Documented the correct format explicitly in `APIS.md`:
`postgresql+asyncpg://user:password@ep-xxx.neon.tech/airp?sslmode=require`.
The `+asyncpg` driver specification is critical — without it, the async
database layer will not function.

### 3. Alpha Vantage 25 req/day limit is very tight

**Problem:** 25 requests/day across a full 8-agent analysis pipeline is
extremely constrained. One analysis could theoretically exhaust the daily quota
if caching is not active.

**Solution:** Documented in `APIS.md` that Alpha Vantage is a supplementary
source only — yFinance covers most fundamentals for free. Added the note that
Redis caching (`CACHE_TTL_FUNDAMENTALS=3600`) is essential for this API, and
that Alpha Vantage calls should be made sparingly and only for data yFinance
does not provide. The rate limit strategy table quantifies the expected calls
per analysis to make this concrete.

### 4. Vercel only exposes VITE_-prefixed env vars to the browser

**Problem:** Adding `CLERK_PUBLISHABLE_KEY` to Vercel's dashboard is not
sufficient — Vite strips all non-`VITE_` prefixed variables from the browser
bundle silently (no error, just `undefined`).

**Solution:** Documented explicitly in the Clerk and Vercel sections that
`CLERK_PUBLISHABLE_KEY` must be duplicated as `VITE_CLERK_PUBLISHABLE_KEY`
in the Vercel dashboard. This mirrors the note in `.env.example` from T-005.

---

## Key Decisions

**Why document yFinance if it needs no key?**
yFinance is the primary data source for price and fundamental data — it does
the most work in the pipeline. Omitting it from `APIS.md` would create a gap
where an engineer might wonder "where does stock data come from?" Every service
AIRP depends on belongs in the reference, key or no key.

**Why a rate limit strategy section?**
The free tier limits only matter if you understand them in the context of real
usage. A raw table of "100 req/day" means nothing without knowing that a
single analysis uses ~3 NewsAPI calls. The strategy section makes the limits
concrete and shows that the Redis caching layer is not optional — it is the
primary mechanism that keeps the system within all free tiers simultaneously.

**Why a sign-up checklist at the bottom?**
Documentation is only useful if it translates to action. A developer cloning
this repo for the first time needs a linear, ordered set of steps to get from
zero to a working local environment. The checklist is that artifact — it maps
directly to the env variables in `.env.example` and can be followed without
reading the entire document.

---

## Learnings

- Clerk's JWT issuer URL is buried in the JWT Templates section — not in the
  main API Keys page. Always navigate there explicitly and document the exact
  path for future reference.
- Neon provides multiple connection string formats (psycopg2, asyncpg, Node.js).
  Always verify the driver suffix matches the async ORM in use.
- Alpha Vantage's 25 req/day limit is the tightest constraint in the entire
  stack. Redis caching must be verified as working before any Phase 1 data
  tool uses Alpha Vantage.
- Rate limits are only meaningful in context. Documenting "calls per analysis"
  alongside the daily limit makes the real constraint visible — and shows where
  caching is critical versus optional.
- The VITE_ prefix rule is a silent failure mode. There is no Vite error when
  a variable is missing the prefix — the value is simply undefined in the
  browser. Documenting this duplication requirement upfront prevents a debugging
  session later.

---

## EOD Update Template

```
EOD Update [Date]:
Completed: T-006
Merged to main: setup/api-keys
Current week: 1 │ Current phase: 0
Blocker (if any): None
Next session: T-007 — [next task name from Excel]
```
