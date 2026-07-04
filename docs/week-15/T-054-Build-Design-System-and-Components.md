# T-054 -- Build Design System and Components

**Phase:** 6 -- React Frontend
**Week:** 15
**Branch:** `feat/ui-design-system`
**Task status:** Complete

---

## Overview

T-054 builds AIRP's reusable component library: eight typed, Tailwind-styled
primitives (Button, Input, Badge, Card, Modal, Spinner, ProgressBar,
Tooltip) that every later Phase 6 page (dashboard, debate viewer, memo
viewer, auth) composes from, instead of each page hand-rolling its own
buttons and cards the way `HomePage.tsx` did in T-053.

**Acceptance criteria (all must pass):**

- All components render correctly
- Storybook or component preview page added

**In scope:** the eight components listed above, a barrel export
(`src/components/ui/index.ts`), an in-app component preview page routed
at `/dev/components`, and a from-scratch Vitest + React Testing Library
test setup with one test file per component.

**Explicitly out of scope** (separate Phase 6 tasks, per the master task
list):

- Storybook itself -- a component preview page satisfies the acceptance
  criterion's "or" without adding a second build tool and dev-server port
  for eight primitives. See "Why a preview page instead of Storybook"
  below.
- The real pages that consume these components (landing, auth, dashboard,
  live progress, debate viewer, results/memo, compare) -- T-055 onward.
- Any data-fetching, form-validation (react-hook-form/zod), or routing
  logic beyond the bare preview page's local `useState` demos.

> **Note on dependencies:** this task adds **six new devDependencies**
> that did not exist in `frontend/package.json` before now: `vitest`,
> `@testing-library/react`, `@testing-library/jest-dom`,
> `@testing-library/user-event`, and `jsdom` -- plus the `test` /
> `test:run` npm scripts. This is a deliberate exception to T-053's
> "no new dependencies" precedent: T-053 explicitly deferred introducing
> a test runner until "there is component behaviour worth testing"
> (see `docs/week-15/T-053-Setup-React-Project.md`), and that point is
> now. Every other dependency (`clsx`, `tailwind-merge`, `react`, ...)
> was already present and is unchanged.

### Why a preview page instead of Storybook

Storybook needs its own config, its own dev server / port, and its own
build step in CI to actually be checked rather than silently rot. For
eight primitives at this stage of the project, an in-app route that
imports the same components the app uses, runs through the same Vite
dev server, and is exercised by the same `npm run build` gives most of
the practical benefit (see everything in one place, catch visual
regressions by eye) for a fraction of the setup and maintenance cost.
This can be revisited if the component count grows enough to justify it.

---

## What Was Built

### Design-system components (`frontend/src/components/ui/`)

#### `Button.tsx` (new)

Variants `primary` / `secondary` / `ghost` / `danger`, sizes `sm` / `md`
/ `lg`, `isLoading` (shows a `Spinner`, forces `disabled` true and sets
`aria-busy`, regardless of what `disabled` was explicitly passed --
loading always wins), `leadingIcon` / `trailingIcon` slots, `fullWidth`.
Built on `ComponentPropsWithoutRef<"button">` via `forwardRef` so every
native button attribute and a real DOM ref both work.

#### `Input.tsx` (new)

A labelled text input wired for `react-hook-form` (`forwardRef` so
`register()` can attach its ref). Required `label` (every field must be
labelled -- no unlabelled inputs in this design system), `error` /
`hint` text, `leadingAddon` / `trailingAddon` slots. `aria-invalid` and
`aria-describedby` are wired automatically: an `error` flips
`aria-invalid` to `true` and links the `role="alert"` message; otherwise
`hint` is linked instead.

#### `Badge.tsx` (new)

Small status/verdict pill. Tones: `neutral`, `brand`, `buy`, `hold`,
`sell` -- the last three map directly to the `verdict.buy/hold/sell`
Tailwind tokens from T-053, formalising the ad hoc verdict chips
`HomePage.tsx` already renders.

#### `Card.tsx` (new)

A compound-component surface container: `Card`, `Card.Header`,
`Card.Title`, `Card.Description`, `Card.Footer`. Matches the
`rounded-card` / `shadow-card` tokens `HomePage.tsx` used ad hoc in
T-053. `noPadding` opts out of the default `p-6` for cards that manage
their own inner spacing.

#### `Modal.tsx` (new)

A centred dialog with a dismissible backdrop. Closes on Escape, on
backdrop click (only when the click target is the backdrop itself, not
a bubbled click from inside the panel), and via a built-in close
button -- all three call the same `onClose`. Locks `document.body`
scroll while open and restores the previous value on close/unmount.
Deliberately does not use `createPortal` (see file header for why);
renders in normal DOM flow, which also keeps it trivially testable.

#### `Spinner.tsx` (new)

A small animated SVG ring, sizes `sm` / `md` / `lg`. Announces
`role="status"` with an `sr-only` "Loading" label by default; when
embedded inside another component that already manages its own busy
announcement (e.g. `Button`'s `aria-busy`), passing `aria-hidden="true"`
suppresses Spinner's own role/label so the two don't double-announce.

#### `ProgressBar.tsx` (new)

A determinate horizontal progress bar -- built for the live
agent-progress dashboard, where each of the 8 agents reports a
`progress_percent` over the WebSocket stream (see
`src/hooks/useAnalysisStream.ts`, T-049). Clamps out-of-range values to
`[0, 100]`, optional `label` and percentage display, full
`role="progressbar"` ARIA wiring.

#### `Tooltip.tsx` (new)

A lightweight hover/focus tooltip, CSS-only positioning (`top` / `bottom`
/ `left` / `right`), no floating-ui/popper dependency. Wraps a single
trigger element via `cloneElement`, injecting `aria-describedby` plus
mouse/focus handlers; the injected-prop shape is captured in a
`TooltipTriggerProps` interface so the `cloneElement` call is fully
typed (no `any` leakage from `ReactElement`'s default generic).

#### `index.ts` (new)

Barrel export: `import { Button, Card, Badge, ... } from "@/components/ui"`
instead of one import line per component file. Re-exports every
component's public prop types alongside the component itself.

### Component preview page

#### `src/pages/ComponentsPreviewPage.tsx` (new)

Every component, every variant, rendered in one page: Button (all 4
variants x loading/disabled/size), Badge (all 5 tones), Input
(default/error/disabled), Card (full compound-component example),
Modal (interactive open/close demo with a destructive-action footer),
Spinner (all 3 sizes), ProgressBar (interactive +/-10% demo across 3
labelled bars), Tooltip (top and bottom placement). Imports from the new
barrel (`@/components/ui`) rather than 8 separate paths.

#### `src/routes/AppRoutes.tsx` (modified)

Adds one route, `path="dev/components"`, nested under `RootLayout`
between the home index and the catch-all 404 (route order matters here
-- the catch-all must stay last). Visit at `/dev/components`; not linked
from the product navigation.

### Testing

#### `frontend/vitest.config.ts` (new)

`mergeConfig`s the existing `vite.config.ts` (so the same path aliases
and the React plugin are reused, not duplicated) with test-only settings:
`environment: "jsdom"`, a setup file, `css: false` (Tailwind class names
are checked directly via `toHaveClass`; actual CSS doesn't need to be
parsed in tests).

#### `src/test/setup.ts` (new)

Imports `@testing-library/jest-dom/vitest` (extends Vitest's `expect`
with `toBeInTheDocument`, `toHaveClass`, etc. -- the Vitest-specific
subpath, not the Jest one) and registers an `afterEach(cleanup)` so one
test's rendered DOM never leaks into the next.

> **Note on `globals`:** Vitest's config supports a `globals: true` mode
> that injects `describe` / `it` / `expect` as ambient globals (no import
> needed). This is deliberately left off, matching the rest of the
> codebase's convention of explicit named imports everywhere (e.g.
> `vite-env.d.ts`'s explicit triple-slash reference rather than an
> implicit global) -- every test file below imports
> `describe, expect, it` (and `vi`, `userEvent`) directly from `vitest`.

#### `*.test.tsx` (new, one per component)

- **`Button.test.tsx`** -- renders its label; `onClick` fires; `disabled`
  blocks the click; `isLoading` sets `aria-busy` and disables the button
  _even when `disabled={false}` is explicitly passed_ (a regression test
  for a real bug caught while building this: the original implementation
  used `disabled ?? isLoading`, which only falls back to `isLoading`
  when `disabled` is `null`/`undefined` -- an explicit `false` would
  have wrongly won and left a loading button clickable; fixed to
  `disabled || isLoading`); all 4 variants render without crashing.
- **`Badge.test.tsx`** -- renders its label; `buy` / `hold` / `sell`
  tones each map to their own distinct background token (not each
  other -- a regression here would mean a SELL verdict rendering green);
  defaults to `neutral`.
- **`Card.test.tsx`** -- the full compound-component API renders
  together; `noPadding` actually removes the default `p-6`.
- **`Input.test.tsx`** -- the visible label is correctly associated with
  the field via `htmlFor`/`id`; typing fires `onChange`; an `error` sets
  `aria-invalid` and renders a linked `role="alert"` message; `hint`
  renders only when there is no error.
- **`Modal.test.tsx`** -- renders nothing while `isOpen` is `false`;
  renders title/body when open; Escape key, the close button, and a
  backdrop click each call `onClose`; a click _inside_ the dialog panel
  does **not** call `onClose`.
- **`ProgressBar.test.tsx`** -- `aria-valuenow` reflects the given value;
  values above 100 / below 0 are clamped; label and rounded-percentage
  text render (or don't, per `showValue`).
- **`Spinner.test.tsx`** -- announces `role="status"` by default; custom
  `label` text renders; `aria-hidden="true"` suppresses the status role
  entirely (the mode `Button` uses internally).
- **`Tooltip.test.tsx`** -- the trigger's `aria-describedby` points at
  the tooltip's `id`; the tooltip is `invisible` until hover, then
  `visible`; keyboard focus shows it and blur hides it again.

### CI

#### `.github/workflows/ci.yml` (modified)

Adds one new step to the frontend job, **"Test -- vitest"**, running
`npm run test:run` (`vitest run` -- a single non-watch pass that exits;
plain `npm run test` / `vitest` with no args starts interactive watch
mode and would hang CI forever). Placed after the Prettier check and
before the production build, so the fast checks fail fast. Job name
updated to `"Frontend — lint, test & build (Node 20)"` to reflect the
new gate.

---

## How It Was Tested / Verified

Backend is untouched by this task, so the backend gate (black, isort,
flake8, mypy, pytest, coverage >= 85) is unaffected.

Frontend, from the `frontend/` directory:

```bash
cd frontend

# 0) New dependencies were added this task — a real install is required
#    (not just npm ci), so package-lock.json picks up the six new
#    devDependencies (vitest, @testing-library/*, jsdom).
npm install

# 1) Auto-fixers FIRST (writes import order + Prettier formatting).
npm run lint:fix
npm run format

# 2) Then the exact checks CI runs — all must exit 0:
npm run type-check      # tsc --noEmit (strict)
npm run lint            # eslint, --max-warnings 0
npm run format:check    # prettier --check src/**
npm run test:run        # vitest run — all component tests
npm run build           # tsc && vite build

# 3) Manual smoke test:
npm run dev             # open http://localhost:3000/dev/components
                        # -> every component variant renders; click
                        # through Button states, open/close the Modal
                        # (Escape, backdrop click, close button, and a
                        # click inside the panel that should NOT close
                        # it), nudge the ProgressBar +/-10%, hover and
                        # tab to the Tooltip triggers.
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
git checkout -b feat/ui-design-system

# 2) (do the work — files listed above)

# 3) Install the new test dependencies, run auto-fixers, then verify
#    (see "How It Was Tested" above)
cd frontend
npm install              # picks up vitest + testing-library + jsdom
npm run lint:fix && npm run format
npm run type-check && npm run lint && npm run format:check
npm run test:run && npm run build
cd ..

# 4) Stage and commit (re-stage after auto-fixers ran)
git add frontend/ .github/workflows/ci.yml docs/week-15/T-054-Build-Design-System-And-Components.md
git commit -m "feat(ui): add AIRP design system components"

# If the pre-commit Prettier/ESLint hook reformats anything, re-stage and
# commit again (two-commit pattern):
#   git add -A && git commit -m "feat(ui): add AIRP design system components"

# 5) Push and open the PR
git push -u origin feat/ui-design-system
```

**Commit message:**

```
feat(ui): add AIRP design system components
```

**PR title:**

```
feat(ui): implement reusable component library with TypeScript and Tailwind
```

**PR description:**

```markdown
## Summary

Builds AIRP's design-system component library: eight typed,
Tailwind-styled primitives (Button, Input, Badge, Card, Modal, Spinner,
ProgressBar, Tooltip) with colour tokens matching the AIRP brand, a
barrel export, and an in-app component preview page at
`/dev/components`. Adds a from-scratch Vitest + React Testing Library
test setup with one test file per component, wired into the frontend CI
gate.

## Changes

- Add `src/components/ui/{Button,Input,Badge,Card,Modal,Spinner,
ProgressBar,Tooltip}.tsx`, each `forwardRef`'d where it wraps a native
  form/interactive element, typed against `ComponentPropsWithoutRef<...>`
  for full native-attribute passthrough
- Add `src/components/ui/index.ts` barrel export
- Add `src/pages/ComponentsPreviewPage.tsx`; wire `path="dev/components"`
  into `src/routes/AppRoutes.tsx`
- Add `vitest.config.ts` (merges `vite.config.ts`), `src/test/setup.ts`,
  and `src/components/ui/*.test.tsx` (one per component)
- `package.json`: add `vitest`, `@testing-library/react`,
  `@testing-library/jest-dom`, `@testing-library/user-event`, `jsdom` as
  devDependencies; add `test` / `test:run` scripts
- `tsconfig.json`: add `vitest.config.ts` to `include`
- CI: add a "Test — vitest" step (`npm run test:run`) to the frontend
  job, between the Prettier check and the production build

## Testing

- [x] Unit tests added / updated — one `*.test.tsx` per component,
      covering rendering, interaction (click/type/hover/focus/Escape), and
      accessibility attributes (`aria-invalid`, `aria-describedby`,
      `aria-busy`, `role="dialog"/"alert"/"status"/"progressbar"/"tooltip"`)
- [x] Integration tests pass (backend untouched; backend gate unaffected)
- [x] Manual smoke test performed (`npm run dev`, `/dev/components`
      route — every variant renders, Modal/Tooltip/ProgressBar interactions
      verified by hand)

`npm run type-check`, `npm run lint`, `npm run format:check`,
`npm run test:run`, and `npm run build` all pass locally.

## LangSmith Trace

n/a — no agent code touched.

## Screenshots

<paste terminal output of the five passing npm checks, and a screenshot
of /dev/components showing all eight component sections>

## Related Issues

Closes #<issue-number>
```

---

## Notes for the Next Task

- Every later Phase 6 page should compose from `@/components/ui` rather
  than hand-rolling buttons/cards the way `HomePage.tsx` did in T-053 --
  consider revisiting `HomePage.tsx` to use the new `Badge` component for
  its verdict chips in a small follow-up, now that one exists.
- `Tooltip` and `Modal` are CSS-only / portal-free by design (see their
  file headers for the rationale). If a future task needs nested
  overlays or viewport-collision-aware positioning, that is the signal
  to introduce `createPortal` and/or a positioning library -- don't
  retrofit it speculatively before that need exists.
- The component preview page is intentionally not part of the production
  navigation. If it should be reachable from the UI in a non-development
  context (e.g. gated behind an env flag), that is a deliberate decision
  for a later task, not an oversight here.
- Next: **T-055**, per the master task list.
