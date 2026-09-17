// frontend/src/components/motion/AnimatedNumber.tsx
// AIRP -- animated KPI number counter (B10)
//
// The work order's "animated number counters on KPIs" micro-interaction:
// counts up from 0 to `value` on mount -- the same "animate in from an
// empty state" pattern ConvictionGauge.tsx already establishes for its
// gauge arc -- then smoothly tweens to each subsequent `value` change
// from wherever it currently sits, using framer-motion's imperative
// `animate()` (not the declarative JSX `animate` prop -- there is no
// motion.div to attach it to here, this renders a plain <span> of
// formatted text, matching how every KPI tile in this codebase already
// renders its number, e.g. AccuracySummaryStats.tsx). `format` lets each
// caller keep its own existing formatting convention (percentages,
// toLocaleString counts, a bare "/10" score) rather than this component
// inventing a new one.
//
// Jumps straight to the final formatted value with no count-up under
// usePrefersReducedMotion(), per the work order's explicit accessibility
// constraint.

import { animate, useMotionValue } from "framer-motion";
import { useEffect, useState } from "react";

import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { cn } from "@/lib/cn";

export interface AnimatedNumberProps {
  /** The number to display. Animates up from 0 on mount, then tweens to each new value. */
  value: number;
  /** Formats the (possibly fractional, mid-tween) number for display. Defaults to Math.round + toLocaleString. */
  format?: (value: number) => string;
  className?: string;
}

const DURATION_SECONDS = 0.8;

function defaultFormat(value: number): string {
  return Math.round(value).toLocaleString("en-IN");
}

/** Counts up from 0 on mount, then tweens to each new `value`. Formatted by `format`. */
export function AnimatedNumber({
  value,
  format = defaultFormat,
  className,
}: AnimatedNumberProps): JSX.Element {
  const prefersReducedMotion = usePrefersReducedMotion();
  const motionValue = useMotionValue(prefersReducedMotion ? value : 0);
  const [displayText, setDisplayText] = useState(() => format(prefersReducedMotion ? value : 0));

  useEffect(() => {
    if (prefersReducedMotion) {
      setDisplayText(format(value));
      motionValue.jump(value);
      return undefined;
    }

    const controls = animate(motionValue, value, {
      duration: DURATION_SECONDS,
      ease: "easeOut",
      onUpdate: (latest) => setDisplayText(format(latest)),
    });
    return () => controls.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- motionValue is a stable ref; format is expected to be referentially stable per caller (a plain function, not recreated per render in this codebase's usage).
  }, [value, prefersReducedMotion]);

  // tabular-nums (a premium-broker-UI baseline, not an opt-in per caller)
  // -- a counting/tweening number must never reflow its own width as
  // digits change, which proportional figures do (a "1" is narrower than
  // an "8"). Always applied, merged with any caller className via cn().
  return <span className={cn("tabular-nums", className)}>{displayText}</span>;
}
