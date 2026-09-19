// frontend/tailwind.config.ts
//
// AIRP design tokens (T-053; ISSUE 5 dark-terminal redesign).
//
// This is the single source of truth for the platform's visual identity.
// Colours, type, radius, and shadow defined here are the vocabulary every
// component builds from -- no component should hard-code a hex value or
// font stack that isn't expressed as a token here.
//
// ISSUE 5 -- why dark, not a light "high-contrast" variant
// -----------------------------------------------------------------------
// The brief asked for the visual language of Indian broker platforms like
// Zerodha Console / Upstox Pro: dense data tables, a dark or high-contrast
// accent palette, tabular figures, and a premium typographic hierarchy.
// AIRP's committee output is fundamentally a trading-terminal-shaped
// product (live agent status, price targets, conviction scores, a
// BUY/HOLD/SELL verdict) -- a near-black canvas with a vivid violet accent
// and saturated verdict colours is the more convincing "premium broker
// terminal" read than a light page with punchier borders, and it is what
// this pass commits to everywhere (no light/dark toggle -- one considered
// look, applied consistently, matching the "do a full pass, not spot
// fixes" instruction). `ink`/`canvas`/`surface`/`muted`/`line` keep their
// EXACT NAMES from the light theme (only redefined here) specifically so
// every existing component -- already disciplined about using only these
// semantic tokens, never a raw hex value -- picks up the new look for
// free, with no per-component edits required. The handful of components
// that assumed a light base (an "inverted dark accent band" that stood
// out against a light page, or an agent-identity accent hue tuned for
// legibility as a light-mode fill) are fixed at their own call sites --
// see DemoCtaSection.tsx, AgentCard.tsx, CommitteeSection.tsx,
// DebateMessageCard.tsx, and LiveGraphView.tsx's own ISSUE 5 comments.
//
// Identity rationale (unchanged from T-053):
//   - `brand` (violet) deliberately matches the "Frontend" layer colour in
//     docs/AIRP_Architecture.drawio, so the running UI and the architecture
//     diagram read as one system. The hue family (50-900) is unchanged --
//     only the handful of call sites that used `brand-50`/`brand-100` as a
//     light chip fill (illegible on a dark canvas) were moved to a
//     translucent `brand-500/…` tint instead, which reads correctly in
//     both themes and needs no new token.
//   - `verdict` (buy/hold/sell) encodes AIRP's core output -- the
//     BUY/HOLD/SELL call from the Portfolio Manager -- as first-class
//     semantic colour, not an afterthought. Brightened one step from the
//     original light-theme values (was tuned as a solid fill behind white
//     text only) so the same three colours also read clearly as bare TEXT
//     against the new dark canvas (see e.g. AgentCard's state badges,
//     which show verdict-family colours as translucent-tinted text, not
//     just solid fills) -- still solid+white-text legible as a Badge fill.
//
// This file is type-checked by tsc (it is in tsconfig "include") but is not
// linted or Prettier-checked (it lives outside src/).

import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Near-black, cool-toned canvas -- the terminal's base layer.
        canvas: "#0A0D14",
        // One step up from canvas: cards, panels, the composer, nav bars.
        surface: "#12161F",
        // Near-white primary text/headings -- kept named "ink" (not
        // "white") so every existing `text-ink` call site is already
        // correct with zero edits.
        ink: "#EAEDF3",
        // Secondary/caption text -- legible but visually quieter than ink.
        muted: "#8A93A6",
        // Borders/dividers -- visible against both canvas and surface
        // without competing with real content.
        line: "#232838",
        brand: {
          50: "#F3F0FE",
          100: "#E7E0FD",
          200: "#CCBFFB",
          300: "#AD98F7",
          400: "#8B6BF0",
          500: "#7C3AED",
          600: "#6D28D9",
          700: "#5B21B6",
          800: "#4C1D95",
          900: "#3B1675",
        },
        verdict: {
          buy: "#10B981",
          hold: "#F59E0B",
          sell: "#EF4444",
        },
        // Secondary accent (landing-page redesign): a muted teal/cyan used
        // sparingly for secondary CTAs, links, and hover/focus states, and
        // to anchor the Assistant section as a distinct "conversational"
        // moment from the primary violet-accented analytical flow.
        // Deliberately NOT reused from `verdict` or `brand` -- it must
        // never be mistakable for a BUY/HOLD/SELL call or the primary
        // brand accent.
        teal: {
          300: "#5EEAD4",
          400: "#2DD4BF",
          500: "#14B8A6",
          600: "#0D9488",
          700: "#0F766E",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Fraunces", "ui-serif", "Georgia", "serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      borderRadius: {
        card: "14px",
      },
      boxShadow: {
        // Dark-canvas shadows read as depth via a near-black ambient
        // shadow PLUS a faint cool-toned glow, rather than the light
        // theme's soft grey shadow (which all but disappears against a
        // dark background) -- the same two-layer "contact + ambient"
        // shape as the original, tuned for the new canvas.
        card: "0 1px 2px rgba(0, 0, 0, 0.4), 0 8px 24px rgba(0, 0, 0, 0.35)",
      },
      maxWidth: {
        memo: "72ch",
      },
    },
  },
  plugins: [],
};

export default config;
