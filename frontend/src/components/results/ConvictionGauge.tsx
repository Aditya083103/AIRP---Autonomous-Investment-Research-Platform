// frontend/src/components/results/ConvictionGauge.tsx
// AIRP -- Conviction gauge (T-061)
//
// A semicircular, animated gauge for InvestmentDecisionResponse's
// conviction_score (1-10) -- the Portfolio Manager's confidence in its
// BUY/HOLD/SELL verdict. Deliberately hand-rolled SVG rather than a
// recharts RadialBarChart: recharts is already a project dependency
// (used elsewhere for time-series/bar data), but a single static arc
// with one animated value is simpler and lighter as plain SVG + a CSS
// transition than as a full chart library instance.
//
// Animation: the arc's `stroke-dashoffset` starts fully "empty" on the
// first render, then a `useEffect` commits the real value one paint
// later, letting the browser's CSS transition animate from empty to
// the actual score -- the standard "animate on mount" pattern. No
// `requestAnimationFrame` is used because the effect firing after the
// initial commit is already sufficient for the transition to be
// observed, and rAF is not reliably polyfilled in the Vitest/jsdom
// test environment.

import { useEffect, useState } from "react";

import { cn } from "@/lib/cn";
import { type Verdict } from "@/types/analysis";

export interface ConvictionGaugeProps {
  /** Portfolio Manager conviction, 1-10. Values outside this range are clamped. */
  score: number;
  /** Determines the arc's colour -- matches the verdict badge's tone. */
  verdict: Verdict;
  className?: string;
}

const VERDICT_STROKE_CLASSES: Record<Verdict, string> = {
  BUY: "stroke-verdict-buy",
  HOLD: "stroke-verdict-hold",
  SELL: "stroke-verdict-sell",
};

// Semicircle path from (20,100) to (180,100) with radius 80.
const GAUGE_PATH = "M20,100 A80,80 0 0 1 180,100";
const ARC_RADIUS = 80;
const ARC_LENGTH = Math.PI * ARC_RADIUS;

/** A semicircular gauge showing the Portfolio Manager's 1-10 conviction score. */
export function ConvictionGauge({ score, verdict, className }: ConvictionGaugeProps): JSX.Element {
  const clampedScore = Math.min(10, Math.max(1, score));
  const filledLength = (ARC_LENGTH * clampedScore) / 10;

  // Starts at 0 (empty arc) and animates to the real value once mounted.
  const [dashOffset, setDashOffset] = useState(ARC_LENGTH);

  useEffect(() => {
    setDashOffset(ARC_LENGTH - filledLength);
  }, [filledLength]);

  return (
    <div className={cn("flex flex-col items-center", className)} data-testid="conviction-gauge">
      <svg
        viewBox="0 0 200 112"
        className="w-full max-w-[220px]"
        role="img"
        aria-label={`Conviction score ${clampedScore} out of 10`}
      >
        <path
          d={GAUGE_PATH}
          fill="none"
          strokeWidth="14"
          strokeLinecap="round"
          className="stroke-line"
        />
        <path
          d={GAUGE_PATH}
          fill="none"
          strokeWidth="14"
          strokeLinecap="round"
          strokeDasharray={ARC_LENGTH}
          strokeDashoffset={dashOffset}
          data-testid="conviction-gauge-fill"
          className={cn(
            "transition-[stroke-dashoffset] duration-700 ease-out",
            VERDICT_STROKE_CLASSES[verdict],
          )}
        />
        <text
          x="92"
          y="90"
          textAnchor="end"
          className="fill-ink font-display text-[32px] font-semibold"
        >
          {clampedScore}
        </text>
        <text x="96" y="90" textAnchor="start" className="fill-muted text-[16px]">
          /10
        </text>
      </svg>
      <p className="mt-1 font-mono text-xs uppercase tracking-wide text-muted">Conviction score</p>
    </div>
  );
}
