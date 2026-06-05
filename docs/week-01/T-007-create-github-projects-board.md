# T-007 — Create GitHub Projects Board

| Field           | Detail                                   |
|-----------------|------------------------------------------|
| **Task ID**     | T-007                                    |
| **Phase**       | 0 — Project Setup & Standards            |
| **Week**        | 1                                        |
| **Branch**      | `setup/project-board`                    |
| **Commit prefix** | `chore: setup project board`           |
| **PR Title**    | `chore: initialise GitHub Projects kanban board` |
| **Priority**    | 🟡 High                                  |
| **Est. Hours**  | 1                                        |
| **Status**      | 🔲 To Do                                 |
| **Depends on**  | T-001 (repo exists), T-002 (folder structure merged) |

---

## Objective

Set up a GitHub Projects (v2) board as the single source of truth for AIRP task
tracking. The board will have four kanban columns — **Backlog**, **In Progress**,
**In Review**, and **Done** — and nine phase-aligned milestones. Every task from
T-001 to T-080 will be represented as a GitHub Issue and loaded into the board.

This gives recruiters and hiring managers a live view of development discipline
when they visit the repository. It also enforces the rule from Section 8.3 of the
Project Overview: _every change goes through a PR that closes at least one GitHub Issue_.

---

## Acceptance Criteria

| Criteria                                                                   | Status |
|----------------------------------------------------------------------------|--------|
| GitHub Projects (v2) board created and linked to the `airp` repository     | 🔲     |
| Board has exactly 4 columns: Backlog / In Progress / In Review / Done      | 🔲     |
| All 9 phase milestones created with titles, descriptions, and no due dates | 🔲     |
| All 80 tasks (T-001 to T-080) exist as GitHub Issues                       | 🔲     |
| Each issue is labelled with its phase, type, and priority                  | 🔲     |
| Each issue is assigned to its correct milestone                             | 🔲     |
| All issues are added to the Project board                                  | 🔲     |
| Completed tasks T-001 to T-006 are in the **Done** column                  | 🔲     |
| T-007 itself is in **In Progress** while this task runs                    | 🔲     |
| Task doc (`T-007-create-github-projects-board.md`) in `docs/week-01/`      | 🔲     |
| PR merged via squash and merge; closes the T-007 issue                     | 🔲     |

---

## Complete Step-by-Step Execution

### Step 1 — Checkout the branch from main

```bash
# Make sure you are on main and it is clean
git checkout main
git pull origin main

# Create the feature branch
git checkout -b setup/project-board

# Verify you are on the correct branch
git branch
# Expected output: * setup/project-board
```

---

### Step 2 — Create the task documentation file

Create this file at `docs/week-01/T-007-create-github-projects-board.md`
(the file you are reading right now). It will be committed at the end of this task.

---

### Step 3 — Create GitHub Labels

Labels must exist before issues are created. Create these labels via
**GitHub → Repository → Issues → Labels → New Label**.

#### Priority labels
| Label name        | Colour  | Description                          |
|-------------------|---------|--------------------------------------|
| `priority: critical` | `#d73a4a` (red)    | Blocking — must be done first     |
| `priority: high`     | `#e4e669` (yellow) | Important, schedule this sprint   |
| `priority: medium`   | `#0075ca` (blue)   | Nice to have, schedule when ready |

#### Type labels
| Label name      | Colour    | Description                             |
|-----------------|-----------|-----------------------------------------|
| `type: feature` | `#0e8a16` | New functionality                       |
| `type: setup`   | `#5319e7` | Project scaffolding and configuration   |
| `type: devops`  | `#b60205` | CI/CD, Docker, deployment               |
| `type: testing` | `#c5def5` | Tests and coverage                      |
| `type: docs`    | `#bfd4f2` | Documentation only                      |
| `type: perf`    | `#fbca04` | Performance improvements                |
| `type: quality` | `#fef2c0` | Code quality, refactoring, cleanup      |

#### Phase labels
| Label name    | Colour    | Description                             |
|---------------|-----------|-----------------------------------------|
| `phase: 0`    | `#ededed` | Project Setup & Standards               |
| `phase: 1`    | `#ededed` | Data Layer & APIs                       |
| `phase: 2`    | `#ededed` | Research Agents                         |
| `phase: 3`    | `#ededed` | LangGraph Orchestration                 |
| `phase: 4`    | `#ededed` | Debate Engine & Advanced Agents         |
| `phase: 5`    | `#ededed` | FastAPI Backend                         |
| `phase: 6`    | `#ededed` | React Frontend                          |
| `phase: 7`    | `#ededed` | Evaluation Framework                    |
| `phase: 8`    | `#ededed` | Polish, Deploy & Launch                 |

---

### Step 4 — Create the 9 Phase Milestones

Navigate to **GitHub → Repository → Issues → Milestones → New Milestone**.
Create each milestone below. Leave due dates blank — AIRP runs on a flexible
24-week timeline.

---

#### Milestone 1: Phase 0 — Project Setup & Standards

**Title:** `Phase 0 — Project Setup & Standards`

**Description:**
```
Establish the engineering foundation for AIRP. By the end of this phase, the
repository is fully configured with CI/CD, pre-commit hooks, documented
environment variables, all external API accounts registered, the GitHub Projects
board active, and initial documentation scaffolded.

Tasks: T-001 to T-008 | Week: 1 | Deliverable: Repo live, CI passing, all accounts active
```

---

#### Milestone 2: Phase 1 — Data Layer & APIs

**Title:** `Phase 1 — Data Layer & APIs`

**Description:**
```
Build and test all LangChain data tools that agents will use to gather
financial, news, and macroeconomic data. Set up PostgreSQL on Neon, ChromaDB
for RAG, and Redis caching. All tools must have unit tests and Redis TTL
caching before Phase 2 begins.

Tasks: T-009 to T-020 | Weeks: 2–4 | Deliverable: All data tools tested and documented
```

---

#### Milestone 3: Phase 2 — Research Agents (4 Agents)

**Title:** `Phase 2 — Research Agents`

**Description:**
```
Build the four parallel research agents: Fundamental Analyst, Technical Analyst,
News Sentiment Agent, and Macro Economist. Each agent must return a validated
Pydantic output model and have its calls traced in LangSmith before this phase
closes.

Tasks: T-021 to T-028 | Weeks: 5–7 | Deliverable: 4 agents live with LangSmith tracing
```

---

#### Milestone 4: Phase 3 — LangGraph Orchestration

**Title:** `Phase 3 — LangGraph Orchestration`

**Description:**
```
Wire all four research agents into a LangGraph StateGraph with the
InvestmentState TypedDict. Implement parallel execution via the Send API,
conditional routing for errors and escalation, and state persistence to
PostgreSQL after every node. Export the Mermaid graph diagram.

Tasks: T-029 to T-036 | Weeks: 8–10 | Deliverable: Full StateGraph with parallel execution
```

---

#### Milestone 5: Phase 4 — Debate Engine & Advanced Agents

**Title:** `Phase 4 — Debate Engine & Advanced Agents`

**Description:**
```
Build the four advanced agents (Risk Officer, Contrarian Investor, Valuation
Agent, Portfolio Manager) and implement the adversarial multi-round debate loop.
Add the Investment Memo generator and PDF export. This phase completes the full
AI pipeline.

Tasks: T-037 to T-044 | Weeks: 11–13 | Deliverable: Full debate loop and downloadable PDF memo
```

---

#### Milestone 6: Phase 5 — FastAPI Backend

**Title:** `Phase 5 — FastAPI Backend`

**Description:**
```
Build the FastAPI backend that exposes the agent pipeline to the frontend.
Includes JWT authentication, the analysis trigger endpoint, status polling,
real-time WebSocket streaming, PDF download, document upload for RAG, and a
full pytest test suite with greater than 85% coverage.

Tasks: T-045 to T-052 | Weeks: 14–16 | Deliverable: All API endpoints live with WebSocket streaming
```

---

#### Milestone 7: Phase 6 — React Frontend

**Title:** `Phase 6 — React Frontend`

**Description:**
```
Build the complete React 18 + TypeScript frontend. Includes the design system,
landing page, auth pages, dashboard, live agent progress viewer (WebSocket),
debate timeline, results page, financial charts, Investment Memo viewer, company
comparison, and full mobile responsiveness.

Tasks: T-053 to T-066 | Weeks: 17–20 | Deliverable: Full UI end-to-end on desktop and mobile
```

---

#### Milestone 8: Phase 7 — Evaluation Framework

**Title:** `Phase 7 — Evaluation Framework`

**Description:**
```
Build LangSmith evaluation suites for the Fundamental Analyst, Sentiment Agent,
and debate loop. Run end-to-end latency benchmarks with a p50 target of under
90 seconds. Document the full evaluation methodology and results in
EVALUATION.md.

Tasks: T-067 to T-072 | Weeks: 21–22 | Deliverable: Eval suites passing, EVALUATION.md complete
```

---

#### Milestone 9: Phase 8 — Polish, Deploy & Launch

**Title:** `Phase 8 — Polish, Deploy & Launch`

**Description:**
```
Dockerise the full stack, deploy backend to Render and frontend to Vercel,
write the production README with demo GIF, record the 3-minute demo video,
run the LinkedIn launch campaign, and update the resume. This milestone marks
project completion.

Tasks: T-073 to T-080 | Weeks: 23–24 | Deliverable: Live public URL, demo video, resume updated
```

---

### Step 5 — Create the GitHub Projects (v2) Board

1. Navigate to **github.com/[your-username]** (your profile, not the repo).
2. Click **Projects → New Project**.
3. Choose **Board** layout.
4. Name it: `AIRP — Development Board`.
5. Click **Create**.
6. In the board settings, link it to the `airp` repository:
   **Settings → Manage Access → Link a Repository → airp**.

#### Configure the four columns

Delete any default columns and create exactly these four, in this order:

| Column name   | Description (add as column note)                         |
|---------------|----------------------------------------------------------|
| **Backlog**   | All tasks not yet started. Ordered by phase then task ID |
| **In Progress** | Task currently being worked on. Max 1–2 items at a time |
| **In Review** | PR is open; waiting for CI to pass                       |
| **Done**      | PR merged to main; issue closed                          |

---

### Step 6 — Create GitHub Issues for All 80 Tasks

Create one GitHub Issue per task. Use this template for every issue title and body:

**Issue title format:** `[T-XXX] Task Title`

**Issue body template:**

```markdown
## Task ID
T-XXX

## Phase & Week
Phase N — Phase Name | Week N

## Description
[Paste task description from the Master Task List]

## Acceptance Criteria
[Paste acceptance criteria from the Master Task List]

## Branch
`branch-name-from-plan`

## Commit Prefix
`type(scope): description`

## PR Title
`type(scope): full pr title`

## Estimated Hours
N hours
```

**Assign labels to each issue:**
- Phase label: `phase: N`
- Type label matching the task type column
- Priority label matching the priority column

**Assign milestone** matching the phase.

---

#### Issues for Phase 0 (T-001 to T-008)

Create these 8 issues and assign them to **Milestone: Phase 0 — Project Setup & Standards**.

| Issue title                                              | Labels                                            |
|----------------------------------------------------------|---------------------------------------------------|
| `[T-001] Initialise GitHub repository`                   | `phase: 0` `type: setup` `priority: critical`     |
| `[T-002] Define folder structure`                        | `phase: 0` `type: setup` `priority: critical`     |
| `[T-003] Configure pre-commit hooks`                     | `phase: 0` `type: devops` `priority: critical`    |
| `[T-004] Setup GitHub Actions CI`                        | `phase: 0` `type: devops` `priority: critical`    |
| `[T-005] Create .env.example`                            | `phase: 0` `type: setup` `priority: critical`     |
| `[T-006] Register all free API accounts`                 | `phase: 0` `type: setup` `priority: critical`     |
| `[T-007] Create GitHub Projects board`                   | `phase: 0` `type: setup` `priority: high`         |
| `[T-008] Write initial documentation`                    | `phase: 0` `type: docs` `priority: high`          |

---

#### Issues for Phase 1 (T-009 to T-020)

Assign to **Milestone: Phase 1 — Data Layer & APIs**.

| Issue title                                              | Labels                                            |
|----------------------------------------------------------|---------------------------------------------------|
| `[T-009] Setup Python backend environment`               | `phase: 1` `type: setup` `priority: critical`     |
| `[T-010] Build fetch_stock_price tool`                   | `phase: 1` `type: feature` `priority: critical`   |
| `[T-011] Build fetch_financials tool`                    | `phase: 1` `type: feature` `priority: critical`   |
| `[T-012] Build fetch_news tool`                          | `phase: 1` `type: feature` `priority: critical`   |
| `[T-013] Build fetch_ratios tool`                        | `phase: 1` `type: feature` `priority: critical`   |
| `[T-014] Build fetch_macro_data tool`                    | `phase: 1` `type: feature` `priority: high`       |
| `[T-015] Build fetch_earnings_transcript tool`           | `phase: 1` `type: feature` `priority: high`       |
| `[T-016] Setup PostgreSQL schema on Neon DB`             | `phase: 1` `type: setup` `priority: critical`     |
| `[T-017] Setup ChromaDB and embedding pipeline`          | `phase: 1` `type: setup` `priority: critical`     |
| `[T-018] Setup Redis caching layer`                      | `phase: 1` `type: setup` `priority: high`         |
| `[T-019] Write data layer integration tests`             | `phase: 1` `type: testing` `priority: high`       |
| `[T-020] Document data layer`                            | `phase: 1` `type: docs` `priority: medium`        |

---

#### Issues for Phase 2 (T-021 to T-028)

Assign to **Milestone: Phase 2 — Research Agents**.

| Issue title                                              | Labels                                            |
|----------------------------------------------------------|---------------------------------------------------|
| `[T-021] Define Pydantic output models for all agents`   | `phase: 2` `type: feature` `priority: critical`   |
| `[T-022] Build Fundamental Analyst agent`                | `phase: 2` `type: feature` `priority: critical`   |
| `[T-023] Build Technical Analyst agent`                  | `phase: 2` `type: feature` `priority: critical`   |
| `[T-024] Build News Sentiment agent`                     | `phase: 2` `type: feature` `priority: critical`   |
| `[T-025] Build Macro Economist agent`                    | `phase: 2` `type: feature` `priority: high`       |
| `[T-026] Connect LangSmith tracing to all agents`        | `phase: 2` `type: devops` `priority: critical`    |
| `[T-027] Write unit tests for all 4 research agents`     | `phase: 2` `type: testing` `priority: critical`   |
| `[T-028] Document agent system prompts and design`       | `phase: 2` `type: docs` `priority: high`          |

---

#### Issues for Phase 3 (T-029 to T-036)

Assign to **Milestone: Phase 3 — LangGraph Orchestration**.

| Issue title                                              | Labels                                            |
|----------------------------------------------------------|---------------------------------------------------|
| `[T-029] Define InvestmentState TypedDict`               | `phase: 3` `type: feature` `priority: critical`   |
| `[T-030] Build LangGraph StateGraph skeleton`            | `phase: 3` `type: feature` `priority: critical`   |
| `[T-031] Implement parallel research agent execution`    | `phase: 3` `type: feature` `priority: critical`   |
| `[T-032] Implement conditional routing logic`            | `phase: 3` `type: feature` `priority: critical`   |
| `[T-033] Implement state persistence`                    | `phase: 3` `type: feature` `priority: high`       |
| `[T-034] Add graph visualisation export`                 | `phase: 3` `type: feature` `priority: medium`     |
| `[T-035] Write LangGraph integration tests`              | `phase: 3` `type: testing` `priority: critical`   |
| `[T-036] Performance profile the pipeline`               | `phase: 3` `type: perf` `priority: high`          |

---

#### Issues for Phase 4 (T-037 to T-044)

Assign to **Milestone: Phase 4 — Debate Engine & Advanced Agents**.

| Issue title                                              | Labels                                            |
|----------------------------------------------------------|---------------------------------------------------|
| `[T-037] Build Risk Officer agent`                       | `phase: 4` `type: feature` `priority: critical`   |
| `[T-038] Build Contrarian Investor agent`                | `phase: 4` `type: feature` `priority: critical`   |
| `[T-039] Build Valuation Agent`                          | `phase: 4` `type: feature` `priority: critical`   |
| `[T-040] Implement multi-round debate loop`              | `phase: 4` `type: feature` `priority: critical`   |
| `[T-041] Build Portfolio Manager agent`                  | `phase: 4` `type: feature` `priority: critical`   |
| `[T-042] Build Investment Memo generator`                | `phase: 4` `type: feature` `priority: critical`   |
| `[T-043] Add PDF export for Investment Memo`             | `phase: 4` `type: feature` `priority: high`       |
| `[T-044] Write tests for debate engine`                  | `phase: 4` `type: testing` `priority: critical`   |

---

#### Issues for Phase 5 (T-045 to T-052)

Assign to **Milestone: Phase 5 — FastAPI Backend**.

| Issue title                                              | Labels                                            |
|----------------------------------------------------------|---------------------------------------------------|
| `[T-045] Setup FastAPI project structure`                | `phase: 5` `type: setup` `priority: critical`     |
| `[T-046] Implement auth with JWT`                        | `phase: 5` `type: feature` `priority: critical`   |
| `[T-047] Build analysis trigger endpoint`                | `phase: 5` `type: feature` `priority: critical`   |
| `[T-048] Build analysis status endpoint`                 | `phase: 5` `type: feature` `priority: critical`   |
| `[T-049] Implement WebSocket for live streaming`         | `phase: 5` `type: feature` `priority: critical`   |
| `[T-050] Build result and PDF endpoints`                 | `phase: 5` `type: feature` `priority: high`       |
| `[T-051] Add document upload endpoint`                   | `phase: 5` `type: feature` `priority: high`       |
| `[T-052] Write API tests with pytest`                    | `phase: 5` `type: testing` `priority: critical`   |

---

#### Issues for Phase 6 (T-053 to T-066)

Assign to **Milestone: Phase 6 — React Frontend**.

| Issue title                                              | Labels                                            |
|----------------------------------------------------------|---------------------------------------------------|
| `[T-053] Setup React project`                            | `phase: 6` `type: setup` `priority: critical`     |
| `[T-054] Build design system and components`             | `phase: 6` `type: feature` `priority: high`       |
| `[T-055] Build Landing Page`                             | `phase: 6` `type: feature` `priority: high`       |
| `[T-056] Build Auth pages`                               | `phase: 6` `type: feature` `priority: critical`   |
| `[T-057] Build Dashboard page`                           | `phase: 6` `type: feature` `priority: high`       |
| `[T-058] Build Analysis Input page`                      | `phase: 6` `type: feature` `priority: critical`   |
| `[T-059] Build live Agent Progress viewer`               | `phase: 6` `type: feature` `priority: critical`   |
| `[T-060] Build Debate Viewer`                            | `phase: 6` `type: feature` `priority: critical`   |
| `[T-061] Build Analysis Results page`                    | `phase: 6` `type: feature` `priority: critical`   |
| `[T-062] Build charts and visualisations`                | `phase: 6` `type: feature` `priority: high`       |
| `[T-063] Build Investment Memo page`                     | `phase: 6` `type: feature` `priority: high`       |
| `[T-064] Build Company Compare page`                     | `phase: 6` `type: feature` `priority: medium`     |
| `[T-065] Responsive design and mobile pass`              | `phase: 6` `type: quality` `priority: high`       |
| `[T-066] Frontend error handling and loading states`     | `phase: 6` `type: quality` `priority: high`       |

---

#### Issues for Phase 7 (T-067 to T-072)

Assign to **Milestone: Phase 7 — Evaluation Framework**.

| Issue title                                              | Labels                                            |
|----------------------------------------------------------|---------------------------------------------------|
| `[T-067] Design LangSmith eval framework`                | `phase: 7` `type: setup` `priority: critical`     |
| `[T-068] Build fundamental analyst eval`                 | `phase: 7` `type: testing` `priority: critical`   |
| `[T-069] Build sentiment eval`                           | `phase: 7` `type: testing` `priority: critical`   |
| `[T-070] Build debate quality eval`                      | `phase: 7` `type: testing` `priority: high`       |
| `[T-071] Build end-to-end latency eval`                  | `phase: 7` `type: perf` `priority: high`          |
| `[T-072] Write EVALUATION.md`                            | `phase: 7` `type: docs` `priority: high`          |

---

#### Issues for Phase 8 (T-073 to T-080)

Assign to **Milestone: Phase 8 — Polish, Deploy & Launch**.

| Issue title                                              | Labels                                            |
|----------------------------------------------------------|---------------------------------------------------|
| `[T-073] Dockerize the full stack`                       | `phase: 8` `type: devops` `priority: critical`    |
| `[T-074] Deploy backend to Render`                       | `phase: 8` `type: devops` `priority: critical`    |
| `[T-075] Deploy frontend to Vercel`                      | `phase: 8` `type: devops` `priority: critical`    |
| `[T-076] Write comprehensive README`                     | `phase: 8` `type: docs` `priority: critical`      |
| `[T-077] Record demo video`                              | `phase: 8` `type: docs` `priority: high`          |
| `[T-078] LinkedIn launch campaign`                       | `phase: 8` `type: docs` `priority: high`          |
| `[T-079] Final code quality pass`                        | `phase: 8` `type: quality` `priority: high`       |
| `[T-080] Update resume and portfolio`                    | `phase: 8` `type: docs` `priority: medium`        |

---

### Step 7 — Add All Issues to the Project Board

1. Open the GitHub Projects board.
2. Click **+ Add Item** at the bottom of the **Backlog** column.
3. Use **#** to search for issues by title and add all 80.
4. Alternatively, use the **Bulk Add** option: click the board's **+** icon → **Add from Repository → airp** → select all open issues.

#### Set initial column placements

| Column        | Issues                                   |
|---------------|------------------------------------------|
| **Done**      | T-001, T-002, T-003, T-004, T-005, T-006 |
| **In Progress** | T-007 (this task, right now)           |
| **Backlog**   | T-008 to T-080                           |

---

### Step 8 — Commit the task documentation file

```bash
# Stage only the task doc — this commit is the deliverable for T-007
git add docs/week-01/T-007-create-github-projects-board.md

git commit -m "chore: setup project board

- Add T-007 task documentation to docs/week-01/
- Documents full GitHub Projects board setup procedure
- Covers all 9 milestones, 80 issues, and kanban column configuration
- Labels and milestone descriptions documented for repo consistency

Closes #7"
```

---

### Step 9 — Push and open the Pull Request

```bash
git push origin setup/project-board
```

Then open a PR on GitHub with the following details.

---

## Pull Request

### Title
```
chore: initialise GitHub Projects kanban board
```

### Description

```markdown
## Summary

Sets up the GitHub Projects (v2) kanban board as the official task-tracking
surface for AIRP. Creates all 9 phase milestones with descriptions, all 80
task issues with labels and milestone assignments, and configures the four
board columns (Backlog / In Progress / In Review / Done).

## Changes

- Created GitHub Projects (v2) board: `AIRP — Development Board`
- Added 4 kanban columns: Backlog, In Progress, In Review, Done
- Created 9 phase milestones (Phase 0 → Phase 8) with full descriptions
- Created 19 labels across three dimensions: phase, type, priority
- Created 80 GitHub Issues (T-001 to T-080) with labels and milestones
- Moved T-001 to T-006 to **Done** column (already merged to main)
- Added `docs/week-01/T-007-create-github-projects-board.md`

## Testing

This task is configuration-only — no code changes. Verified by:
- Board visible at github.com/[username]/airp/projects
- All 9 milestones visible at github.com/[username]/airp/milestones
- All 80 issues visible and labelled under Issues tab
- CI passes (no source code changed)

## LangSmith Trace

N/A — no agent code in this PR.

## Screenshots

- [ ] Screenshot of the kanban board with all 4 columns
- [ ] Screenshot of the Milestones page showing all 9 milestones

## Related Issues

Closes #7
```

### Merge strategy
Squash and merge. Delete branch after merge.

---

## Post-Merge Checklist

After the PR is merged:

- [ ] Move T-007 issue to **Done** on the board
- [ ] Move T-008 issue to **In Progress** (next task)
- [ ] Verify all 9 milestones show correct open/closed issue counts
- [ ] Update the weekly sprint log if you are tracking hours

---

## Notes for Future Sessions

- Every new task branch should immediately move its corresponding issue to **In Progress**.
- When a PR is opened, move the issue to **In Review**.
- When the PR is merged, GitHub automatically closes the issue if the PR description contains `Closes #N`.
- Never leave more than 2 issues in **In Progress** at the same time — it signals context-switching, which slows delivery.
- The board URL should be added to the repository's sidebar (**About → Website** or as a pinned project) so recruiters find it without searching.

---

*End of T-007 — AIRP Project Documentation | Phase 0, Week 1*
