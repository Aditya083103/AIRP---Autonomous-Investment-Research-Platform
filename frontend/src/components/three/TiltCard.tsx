// frontend/src/components/three/TiltCard.tsx
// AIRP -- pointer-tracked 3D tilt wrapper (B10)
//
// The work order's "subtle 3D tilt/parallax on key cards" requirement,
// deliberately implemented as CSS 3D transforms driven by pointer
// position (framer-motion's useMotionValue/useTransform/useSpring)
// rather than a WebGL/react-three-fiber mount per card -- mounting a
// <Canvas> per card on a page with several of them (Compare's two
// panels, Accuracy's stat tiles, the landing committee grid) would
// multiply GPU context creation and bundle-parse cost for an effect a
// few degrees of CSS perspective already delivers convincingly.
// HeroScene.tsx is the one place real WebGL 3D earns its place -- a
// single hero, not a per-card multiply.
//
// Renders a plain, untilted wrapper under usePrefersReducedMotion(), per
// the work order's explicit accessibility constraint.

import { motion, useMotionValue, useSpring, useTransform, type MotionValue } from "framer-motion";
import { type PointerEvent, type ReactNode } from "react";

import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";

export interface TiltCardProps {
  children: ReactNode;
  className?: string;
}

const MAX_TILT_DEGREES = 6;
const SPRING_CONFIG = { stiffness: 200, damping: 20, mass: 0.5 };
const PERSPECTIVE_PIXELS = 800;

function useTiltAxis(pointerAxis: MotionValue<number>): MotionValue<number> {
  const rawDegrees = useTransform(pointerAxis, [-0.5, 0.5], [MAX_TILT_DEGREES, -MAX_TILT_DEGREES]);
  return useSpring(rawDegrees, SPRING_CONFIG);
}

/** Tilts its child in 3D toward the pointer on hover. A plain wrapper under reduced motion. */
export function TiltCard({ children, className }: TiltCardProps): JSX.Element {
  const prefersReducedMotion = usePrefersReducedMotion();
  const pointerX = useMotionValue(0);
  const pointerY = useMotionValue(0);
  const rotateX = useTiltAxis(pointerY);
  const rotateY = useTiltAxis(pointerX);

  if (prefersReducedMotion) {
    return <div className={className}>{children}</div>;
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>): void {
    const bounds = event.currentTarget.getBoundingClientRect();
    if (bounds.width === 0 || bounds.height === 0) {
      return;
    }
    pointerX.set((event.clientX - bounds.left) / bounds.width - 0.5);
    pointerY.set((event.clientY - bounds.top) / bounds.height - 0.5);
  }

  function handlePointerLeave(): void {
    pointerX.set(0);
    pointerY.set(0);
  }

  return (
    <motion.div
      className={className}
      data-testid="tilt-card"
      style={{ rotateX, rotateY, transformPerspective: PERSPECTIVE_PIXELS }}
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
    >
      {children}
    </motion.div>
  );
}
