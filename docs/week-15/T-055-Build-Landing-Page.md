# T-055 -- Build Landing Page

**Phase:** 6 -- React Frontend
**Week:** 15
**Branch:** `feat/ui-landing`
**Task status:** Complete

---

## Overview

T-055 replaces the small foundation page T-053 shipped at `/` with AIRP's
real marketing landing page: a hero, the 8-agent committee diagram, a
how-it-works walkthrough, a dedicated live-demo call-to-action, a
tech-stack section, and a content footer with an investment-advice
disclaimer. Every section composes from the `@/components/ui` primitives
T-054 built rather than hand-rolling markup, and every section lives in
its own file under `src/components/landing/` so `HomePage.tsx` stays pure
composition.

**Acceptance criteria (all must pass):**

- Page renders on mobile and desktop
- CTA links to analysis page
- No layout bugs

**In scope:** the six landing sections (hero, committee/feature
highlights, how-it-works, live-demo CTA, tech stack, footer), a
placeholder `/analysis` route so the CTAs have somewhere real to go, and
one test file per section plus an integration test for `HomePage`.

**Explicitly out of scope** (separate Phase 6 tasks, per the master task
list):

- The real Analysis Input page (company autocomplete, PDF upload,
  validation) -- that is T-058. `/analysis` is a small, honest
  placeholder here, not a fake form.
- Header navigation / auth menu -- `RootLayout`'s header is untouched;
  a nav overhaul is a reasonable follow-up once T-056 (auth pages) exists
  to link to, but is not part of this task.
- Any data fetching. Every number and status on the page (the hero's
  "Example output" card) is static, hardcoded, and clearly labelled as an
  example -- there is no live backend call from the landing page.

> **Note on dependencies:** this task adds **zero** new dependencies.
> The "tech stack logos" requirement is met with plain-text wordmark
> chips (`TechStackSection.tsx`) rather than fetched brand-logo image
> assets -- no icon library, no logo CDN, nothing that isn't already in
> `package.json`.

---

## What Was Built

### Landing sections (`frontend/src/components/landing/`)

#### `HeroSection.tsx` (new)

Headline, subhead, and two CTAs: a primary "Run a live analysis" button
(`Link` to `/analysis`) and a secondary "See how it works" anchor
(`<a href="#how-it-works">` -- a plain anchor, not a router `Link`, so
the browser's native same-page scroll-to behaviour actually fires; `Link`
does not scroll on a hash-only `to`). Signature visual: a static
"Example output" card modelled on the real product mechanic -- 8 status
dots for the committee and a `Badge tone="buy"` verdict with a conviction
score -- instead of a generic stat block. Labelled "Example output" in
two places so it never reads as a live recommendation.

#### `CommitteeSection.tsx` (new)

The "8 agents diagram" acceptance criterion. Deliberately mirrors
`docs/AIRP_Architecture.drawio`'s colour legend instead of inventing a new
one: research agents (`Fundamental Analyst`, `Technical Analyst`,
`News Sentiment Agent`, `Macro Economist`) keep the diagram's `#1D4ED8`;
the debate/challenge agents (`Risk Officer`, `Contrarian Investor`,
`Valuation Agent`) keep `#B91C1C`; `Portfolio Manager` keeps `#065F46`.
Grouped into the three rounds the LangGraph pipeline actually runs in
(parallel research -> debate -> final call), each agent card showing its
seat number, mandate, tools, and Pydantic output type straight from
`AIRP_Project_Overview_Updated.docx` section 3.

#### `HowItWorksSection.tsx` (new)

The "how-it-works steps" acceptance criterion. A genuinely ordered
5-step `<ol>` (numbered `01`-`05`) condensed from the overview doc's
section 4.2 "Request Flow" -- numbering is justified here (unlike the
committee section, which is grouped by round, not sequence) because this
content really is a pipeline a user's request passes through.

#### `DemoCtaSection.tsx` (new)

The "live demo CTA" acceptance criterion as its own dedicated,
high-contrast band (dark `bg-ink` card) further down the page, separate
from the hero's CTA -- so a reader who scrolled past the hero to read the
committee and how-it-works sections first still has an obvious next step.
Links to `/analysis`.

#### `TechStackSection.tsx` (new)

The "tech stack logos" acceptance criterion, rendered as text wordmark
chips (React 18, TypeScript, Tailwind CSS, FastAPI, LangGraph, LangChain,
PostgreSQL, ChromaDB, Redis, Groq Llama 3.3) instead of fetched brand-logo
image assets -- no `<img>` in this section at all (covered by its test).

#### `LandingFooter.tsx` (new)

The "footer" acceptance criterion: a rich content footer (an AIRP blurb,
a Product link column, a Project link column with the GitHub repo) plus a
plain-language disclaimer ("Educational portfolio project ... not
investment advice"). This is the page's _content_ footer, rendered inside
`<main>` as the landing page's last section -- it is intentionally
separate from `RootLayout`'s existing slim chrome footer ("Built as a
portfolio project...") which still renders below it on every route. That
two-tier pattern (rich footer content, then a thin copyright bar) is how
most real marketing sites are structured, not an accidental duplicate
footer. Internal links use a router `Link`, the hash anchors use plain
`<a>` (same reason as the hero's secondary CTA), and the external GitHub
link opens with `target="_blank" rel="noreferrer"`.

#### `index.ts` (new)

Barrel export for the six sections, mirroring
`src/components/ui/index.ts`'s pattern from T-054.

### Pages

#### `src/pages/HomePage.tsx` (rewritten)

T-053's small foundation page is replaced with the real composition: the
six landing sections in reading order, nothing else. HomePage owns no
content of its own now -- every section is independently testable and
independently owned by its own file.

#### `src/pages/AnalysisPage.tsx` (new)

A small, honest placeholder at `/analysis` -- the target of both CTAs.
States plainly that the real form lands in T-058/T-059 and links back to
`#how-it-works`. Not linked from the header nav or footer as a finished
feature; it exists purely so the CTAs are not dead links.

#### `src/routes/AppRoutes.tsx` (modified)

Adds `<Route path="analysis" element={<AnalysisPage />} />` between the
home index and the `/dev/components` preview route.

### Testing

One test file per section plus two integration tests, in
`frontend/src/test/` (matching T-054's flat test-folder convention, not
colocated):

- **`HeroSection.test.tsx`** -- headline renders; primary CTA points at
  `/analysis`; secondary CTA points at `#how-it-works`; the preview card
  is labelled "Example output".
- **`CommitteeSection.test.tsx`** -- all 8 agents render by name; all 3
  round headings render; seat numbers render (a regression guard against
  an agent silently dropping off the committee).
- **`HowItWorksSection.test.tsx`** -- exactly 5 list items; the `01`-`05`
  numbers appear in document order; the final step names the Portfolio
  Manager's decision.
- **`DemoCtaSection.test.tsx`** -- heading renders; CTA points at
  `/analysis`.
- **`TechStackSection.test.tsx`** -- the heading and a sample of chips
  render; asserts zero `<img>` elements in the section (guards the
  "no fetched logo assets" decision above).
- **`LandingFooter.test.tsx`** -- the GitHub link has
  `target="_blank"`/`rel="noreferrer"`; internal links do not; the
  not-investment-advice disclaimer renders.
- **`HomePage.test.tsx`** -- integration test: all six sections are
  present when composed together, and there is exactly one `<h1>` on the
  page (an accessibility/SEO regression guard for the composition itself).
- **`AnalysisPage.test.tsx`** -- the coming-soon heading renders; the
  back-link points at `/#how-it-works`.

### CI

No workflow changes -- the frontend job's existing five gates
(`type-check`, `lint`, `format:check`, `test:run`, `build`) already cover
new `src/**/*.{ts,tsx}` files and new `*.test.tsx` files with zero
modification, since no new dependency or script was introduced.

---

## How It Was Tested / Verified

Backend is untouched by this task, so the backend gate (black, isort,
flake8, mypy, pytest, coverage >= 85) is unaffected.

Frontend, from the `frontend/` directory:

```bash
cd frontend

# 0) No new dependencies this task -- npm ci is enough (unlike T-054,
#    which needed npm install to pick up new devDependencies).
npm ci

# 1) Auto-fixers FIRST (writes import order + Prettier formatting).
npm run lint:fix
npm run format

# 2) Then the exact checks CI runs -- all must exit 0:
npm run type-check      # tsc --noEmit (strict)
npm run lint            # eslint, --max-warnings 0
npm run format:check    # prettier --check src/**
npm run test:run        # vitest run -- all component + page tests
npm run build           # tsc && vite build

# 3) Manual smoke test:
npm run dev             # open http://localhost:3000/
                        # -> hero renders with both CTAs; click "See how
                        # it works" and confirm the page scrolls to the
                        # how-it-works section; click "Run a live
                        # analysis" and confirm it navigates to
                        # /analysis without a full page reload; resize
                        # the viewport down to a phone width (375px) and
                        # confirm the hero, committee grid, and footer
                        # columns all reflow to a single column with no
                        # overlapping text or horizontal scrollbar.
```

> Run step 1 before committing. The pre-commit Prettier hook also
> rewrites files on commit (the established two-commit flow), but on
> Windows the hook shims can be blocked by App Control -- running
> `npm run format` / `npm run lint:fix` by hand guarantees the committed
> files are clean regardless, and the CI `*:check` / `test:run` jobs are
> the real gate.

---

## Git Workflow (exact commands)

```bash
# 0) Start from an up-to-date main
git checkout main
git pull origin main

# 1) Create the feature branch
git checkout -b feat/ui-landing

# 2) (do the work -- files listed above)

# 3) Run auto-fixers, then verify (see "How It Was Tested" above)
cd frontend
npm ci
npm run lint:fix && npm run format
npm run type-check && npm run lint && npm run format:check
npm run test:run && npm run build
cd ..

# 4) Stage and commit (re-stage after auto-fixers ran)
git add frontend/src/components/landing/ \
        frontend/src/pages/HomePage.tsx \
        frontend/src/pages/AnalysisPage.tsx \
        frontend/src/routes/AppRoutes.tsx \
        frontend/src/test/HeroSection.test.tsx \
        frontend/src/test/CommitteeSection.test.tsx \
        frontend/src/test/HowItWorksSection.test.tsx \
        frontend/src/test/DemoCtaSection.test.tsx \
        frontend/src/test/TechStackSection.test.tsx \
        frontend/src/test/LandingFooter.test.tsx \
        frontend/src/test/HomePage.test.tsx \
        frontend/src/test/AnalysisPage.test.tsx \
        docs/week-15/T-055-Build-Landing-Page.md
git commit -m "feat(ui): build AIRP marketing landing page"

# If the pre-commit Prettier/ESLint hook reformats anything, re-stage and
# commit again (two-commit pattern):
#   git add -A && git commit -m "feat(ui): build AIRP marketing landing page"

# 5) Push and open the PR
git push -u origin feat/ui-landing
```

**Commit message:**

```
feat(ui): build AIRP marketing landing page
```

**PR title:**

```
feat(ui): implement marketing landing page with 8-agent committee diagram
```

**PR description:**

```markdown
## Summary

Replaces the T-053 foundation home page with AIRP's real marketing
landing page: a hero with a static example-output preview, an 8-agent
committee diagram colour-matched to the architecture doc, a 5-step
how-it-works walkthrough, a dedicated live-demo CTA band, a tech-stack
section, and a content footer with an investment-advice disclaimer. Adds
a placeholder `/analysis` route so both CTAs resolve to a real page ahead
of the full Analysis Input page in T-058.

## Changes

- Add `src/components/landing/{HeroSection,CommitteeSection,
HowItWorksSection,DemoCtaSection,TechStackSection,LandingFooter}.tsx`
  plus a barrel `index.ts`, composed entirely from existing
  `@/components/ui` primitives (T-054) -- zero new dependencies
- Rewrite `src/pages/HomePage.tsx` to compose the six sections
- Add `src/pages/AnalysisPage.tsx` (placeholder; real form is T-058) and
  wire `path="analysis"` into `src/routes/AppRoutes.tsx`
- Add `src/test/{HeroSection,CommitteeSection,HowItWorksSection,
DemoCtaSection,TechStackSection,LandingFooter,HomePage,
AnalysisPage}.test.tsx`

## Testing

- [x] Unit tests added / updated -- one `*.test.tsx` per landing section
      plus integration tests for `HomePage` (all sections compose, exactly
      one `<h1>`) and `AnalysisPage`
- [x] Integration tests pass (backend untouched; backend gate unaffected)
- [x] Manual smoke test performed (`npm run dev`, `/` -- hero CTAs
      verified, hash-anchor scroll confirmed, responsive reflow checked at
      375px width, no horizontal scrollbar or overlapping text)

`npm run type-check`, `npm run lint`, `npm run format:check`,
`npm run test:run`, and `npm run build` all pass locally.

## LangSmith Trace

n/a -- no agent code touched.

## Screenshots

<paste terminal output of the five passing npm checks, plus desktop and
375px-wide mobile screenshots of the landing page>

## Related Issues

Closes #<issue-number>
```

---

## Notes for the Next Task

- `AnalysisPage.tsx` is a placeholder on purpose -- T-058 replaces its
  body entirely with the real company-search/upload form. Don't extend
  the placeholder with partial functionality; either it's the real page
  or it stays a one-screen "coming soon" notice.
- `CommitteeSection`'s per-agent accent colours (`#1D4ED8` / `#B91C1C` /
  `#065F46`) are arbitrary Tailwind values deliberately copied from
  `AIRP_Architecture.drawio`, not new design tokens in
  `tailwind.config.ts`. If a future task needs these same three colours
  in a second place (e.g. the debate viewer in a later task colour-coding
  agent messages by role), that repetition is the signal to promote them
  into the token config -- don't do it speculatively here for a single
  section.
- The header (`RootLayout`)'s "Phase 6 - Frontend" badge is untouched.
  Once T-056 (auth pages) exists, a small follow-up could turn the header
  into a real nav bar with a "Log in" link -- not done here to avoid
  wiring a route that still 404s.
- Next: **T-056 -- Build Auth pages**, per the master task list.
