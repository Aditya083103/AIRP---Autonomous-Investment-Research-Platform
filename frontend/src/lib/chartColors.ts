// frontend/src/lib/chartColors.ts
// AIRP -- Recharts colour constants (T-062; ISSUE 5 dark-terminal redesign)
//
// Recharts' SVG props (stroke, fill) need literal colour values, not
// Tailwind utility classes -- Tailwind's generated classes aren't
// importable as JS values. This file is the single place those
// literals live, hand-kept in sync with tailwind.config.ts's `colors`
// token block so every chart uses the exact same palette the rest of
// the UI does rather than each chart component picking its own hex
// values.
//
// ISSUE 5: this file was the one place the light-theme -> dark-theme
// token swap in tailwind.config.ts could NOT reach automatically --
// every other component reads colour via a Tailwind class (recompiled
// against the new token values for free), but Recharts needs these as
// plain JS string literals, so they have to be updated by hand here,
// to the EXACT same values tailwind.config.ts now defines. Every
// chart in the app (revenue/profit, price history, risk radar,
// sentiment gauge, accuracy trend, peer valuation, conviction scatter)
// imports from this one file, so this is the single edit that re-skins
// all of them at once.

export const CHART_COLORS = {
  brand: "#7C3AED",
  brandDark: "#5B21B6",
  brandLight: "#CCBFFB",
  buy: "#10B981",
  hold: "#F59E0B",
  sell: "#EF4444",
  ink: "#EAEDF3",
  muted: "#8A93A6",
  line: "#232838",
} as const;
