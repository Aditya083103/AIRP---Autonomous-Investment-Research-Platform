// frontend/tailwind.config.ts
//
// AIRP design tokens (T-053 dark-terminal pass, superseded by this
// broker-app light redesign).
//
// This is the single source of truth for the platform's visual identity.
// Colours, type, radius, and shadow defined here are the vocabulary every
// component builds from -- no component should hard-code a hex value or
// font stack that isn't expressed as a token here.
//
// Broker-app redesign -- why light, not the old dark terminal
// -----------------------------------------------------------------------
// User feedback: the previous all-dark canvas with a glowing violet accent,
// a 3D hero scene, and soft glassy cards read as a generic "AI startup"
// look, not a real trading platform -- and violet/purple specifically is
// the single most recognisable "AI wrapper product" accent colour in
// current web design. Real Indian broker platforms (Zerodha Kite, Upstox
// Pro, Angel One) are overwhelmingly light: a near-white canvas, white
// cards separated by hairline borders rather than heavy shadow/glow, dense
// data tables, tabular-figure numerics, and ONE restrained accent colour
// used sparingly for links/active-states/primary actions -- never a
// gradient. This pass moves the whole app to that palette. `ink`/`canvas`/
// `surface`/`muted`/`line` keep their EXACT NAMES from every prior pass
// (only redefined here) specifically so every existing component --
// already disciplined about using only these semantic tokens, never a raw
// hex value -- picks up the new look for free, with no per-component edits
// required. The handful of components that special-cased the DARK canvas
// (a translucent glow tint, an "inverted accent band" that only worked
// against a light OR dark base for opposite reasons, or a hue tuned for
// legibility against black) needed their own follow-up edit here too --
// see DemoCtaSection.tsx, AgentCard.tsx, CommitteeSection.tsx,
// DebateMessageCard.tsx, LiveGraphView.tsx, HeroSceneCanvas.tsx, Badge.tsx,
// Modal.tsx, and Tooltip.tsx's own comments on this redesign.
//
// Identity rationale:
//   - `brand` is now a restrained blue (Zerodha Kite's own accent family),
//     replacing the previous violet. Used the same way real broker UIs use
//     their one accent: primary buttons, links, active nav/tab state, and
//     focus rings -- never as a decorative gradient or glow.
//   - `verdict` (buy/hold/sell) still encodes AIRP's core output -- the
//     BUY/HOLD/SELL call from the Portfolio Manager -- as first-class
//     semantic colour. Deepened one step from the dark-theme values (which
//     were brightened specifically to read against near-black) so the same
//     three colours have correct contrast as text on a white/near-white
//     surface instead.
//   - Display headings no longer use a separate serif font -- pairing a
//     decorative serif display face with a sans body is itself a common
//     "generated landing page" tell. `display` now resolves to the same
//     Inter stack as `sans`, at a heavier weight, matching how Kite/Upstox
//     set their own headings (one grotesk family, weight does the work).
//
// This file is type-checked by tsc (it is in tsconfig "include") but is not
// linted or Prettier-checked (it lives outside src/).

import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Near-white, cool-toned canvas -- the page background behind cards.
        canvas: "#F4F6F9",
        // Cards, panels, the composer, nav bars -- pure white, separated
        // from canvas by a hairline border rather than shadow/elevation.
        surface: "#FFFFFF",
        // Near-black primary text/headings -- kept named "ink" (not
        // "black") so every existing `text-ink` call site is already
        // correct with zero edits.
        ink: "#12151C",
        // Secondary/caption text -- legible but visually quieter than ink.
        muted: "#666E7D",
        // Borders/dividers -- a visible hairline against both canvas and
        // surface without competing with real content; this is the
        // PRIMARY way cards read as separate from the page in this
        // redesign, not shadow.
        line: "#DFE3E9",
        brand: {
          50: "#EAF2FC",
          100: "#D3E5F8",
          200: "#A8CBF1",
          300: "#7CB0EA",
          400: "#4C90E0",
          500: "#2B77CB",
          600: "#1F5FA8",
          700: "#184A82",
          800: "#123762",
          900: "#0B2440",
        },
        verdict: {
          buy: "#0E9F5E",
          hold: "#C2760A",
          sell: "#D5342B",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      borderRadius: {
        card: "8px",
      },
      boxShadow: {
        // A near-flat, hairline-first elevation: cards are told apart by
        // `border-line` (see above), and this shadow is only a faint
        // contact shadow to lift interactive surfaces (menus, the chat
        // composer) a single step off the page -- not the dark theme's
        // heavy two-layer glow.
        card: "0 1px 2px rgba(18, 21, 28, 0.06), 0 1px 1px rgba(18, 21, 28, 0.04)",
      },
      maxWidth: {
        memo: "72ch",
      },
    },
  },
  plugins: [],
};

export default config;
