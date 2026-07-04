// frontend/src/lib/chartColors.ts
// AIRP -- Recharts colour constants (T-062)
//
// Recharts' SVG props (stroke, fill) need literal colour values, not
// Tailwind utility classes -- Tailwind's generated classes aren't
// importable as JS values. This file is the single place those
// literals live, hand-kept in sync with tailwind.config.ts's `colors`
// token block so every chart uses the exact same palette the rest of
// the UI does rather than each chart component picking its own hex
// values.

export const CHART_COLORS = {
  brand: "#7C3AED",
  brandDark: "#5B21B6",
  brandLight: "#CCBFFB",
  buy: "#059669",
  hold: "#D97706",
  sell: "#DC2626",
  ink: "#0B1220",
  muted: "#5B6472",
  line: "#E2E5EA",
} as const;
