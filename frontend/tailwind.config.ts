// frontend/tailwind.config.ts
//
// AIRP design tokens (T-053).
//
// This is the single source of truth for the platform's visual identity.
// Colours, type, radius, and shadow defined here are the vocabulary every
// Phase 6 component (T-053-T-066) builds from -- no component should
// hard-code a hex value or font stack that isn't expressed as a token here.
//
// Identity rationale:
//   - `brand` (violet) deliberately matches the "Frontend" layer colour in
//     docs/AIRP_Architecture.drawio, so the running UI and the architecture
//     diagram read as one system.
//   - `verdict` (buy/hold/sell) encodes AIRP's core output -- the
//     BUY/HOLD/SELL call from the Portfolio Manager -- as first-class
//     semantic colour, not an afterthought.
//
// This file is type-checked by tsc (it is in tsconfig "include") but is not
// linted or Prettier-checked (it lives outside src/).

import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0B1220",
        canvas: "#F4F5F7",
        surface: "#FFFFFF",
        muted: "#5B6472",
        line: "#E2E5EA",
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
          buy: "#059669",
          hold: "#D97706",
          sell: "#DC2626",
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
        card: "0 1px 2px rgba(11, 18, 32, 0.04), 0 8px 24px rgba(11, 18, 32, 0.06)",
      },
      maxWidth: {
        memo: "72ch",
      },
    },
  },
  plugins: [],
};

export default config;
