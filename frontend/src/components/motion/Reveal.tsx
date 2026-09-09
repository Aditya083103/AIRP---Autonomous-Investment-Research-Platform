// frontend/src/components/motion/Reveal.tsx
// AIRP -- staggered entrance wrapper (B10)
//
// The work order's "staggered card entrances" micro-interaction: fades
// and rises a single child in on mount, with an optional `index` used to
// cascade a whole list (each item's delay = index * STAGGER_STEP_SECONDS,
// capped at MAX_STAGGER_DELAY_SECONDS so a long list doesn't leave its
// last cards waiting seconds to appear). Deliberately animates on mount
// (`initial`+`animate`) rather than on-scroll (`whileInView`) -- the
// latter needs IntersectionObserver, which jsdom does not implement, and
// an on-mount entrance already covers every real use here (agent cards
// appearing as a live run progresses, KPI tiles appearing once a query
// resolves, landing-page sections that are already in the initial
// viewport on a typical desktop load).
//
// Renders a plain, unanimated wrapper instead when
// usePrefersReducedMotion() reports true, per the work order's explicit
// accessibility constraint.

import { motion } from "framer-motion";
import { type ReactNode } from "react";

import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";

export interface RevealProps {
  children: ReactNode;
  /** Position within a list -- multiplied into a cascading entrance delay. Defaults to 0. */
  index?: number;
  className?: string;
}

const STAGGER_STEP_SECONDS = 0.06;
const MAX_STAGGER_DELAY_SECONDS = 0.4;
const DURATION_SECONDS = 0.45;
const RISE_PIXELS = 16;

/** Fades and rises its child in on mount, staggered by `index`. A no-op under reduced motion. */
export function Reveal({ children, index = 0, className }: RevealProps): JSX.Element {
  const prefersReducedMotion = usePrefersReducedMotion();

  if (prefersReducedMotion) {
    return <div className={className}>{children}</div>;
  }

  const delay = Math.min(index * STAGGER_STEP_SECONDS, MAX_STAGGER_DELAY_SECONDS);

  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: RISE_PIXELS }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: DURATION_SECONDS, delay, ease: "easeOut" }}
    >
      {children}
    </motion.div>
  );
}
