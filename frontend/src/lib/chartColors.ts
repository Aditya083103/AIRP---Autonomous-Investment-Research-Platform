// frontend/src/lib/chartColors.ts
// AIRP -- Recharts colour constants (T-062, re-skinned for the broker-app
// light redesign)
//
// Recharts' SVG props (stroke, fill) need literal colour values, not
// Tailwind utility classes -- Tailwind's generated classes aren't
// importable as JS values. This file is the single place those
// literals live, hand-kept in sync with tailwind.config.ts's `colors`
// token block so every chart uses the exact same palette the rest of
// the UI does rather than each chart component picking its own hex
// values.
//
// This file is the one place a Tailwind token change (tailwind.config.ts)
// does NOT propagate automatically -- every other component reads colour
// via a Tailwind class (recompiled against the new token values for
// free), but Recharts needs these as plain JS string literals, so they
// have to be updated by hand here, to the EXACT same values
// tailwind.config.ts defines. Every chart in the app (revenue/profit,
// price history, risk radar, sentiment gauge, accuracy trend, peer
// valuation, conviction scatter) imports from this one file, so this is
// the single edit that re-skins all of them at once.

export const CHART_COLORS = {
  brand: "#2B77CB",
  brandDark: "#184A82",
  brandLight: "#A8CBF1",
  buy: "#0E9F5E",
  hold: "#C2760A",
  sell: "#D5342B",
  ink: "#12151C",
  muted: "#666E7D",
  line: "#DFE3E9",
} as const;
