// frontend/src/components/three/HeroScene.tsx
// AIRP -- lazy-loaded, capability-gated 3D hero mount (B10)
//
// Public entry point for the landing hero's 3D treatment. The actual
// react-three-fiber scene (HeroSceneCanvas.tsx) is dynamically
// import()-ed -- code-split into its own chunk by Vite/Rollup -- and
// only requested at all when BOTH gates below pass, so three.js/
// @react-three/fiber/drei never load into a browser that would not
// render them anyway:
//
//   1. prefers-reduced-motion is NOT set (usePrefersReducedMotion) --
//      the work order's explicit accessibility constraint.
//   2. WebGL is actually available (useWebglSupported) -- a cheap
//      synchronous canvas.getContext probe, false in jsdom (so this
//      also naturally keeps three.js out of every component test, with
//      no need to mock it) and on the rare browser/device without
//      WebGL.
//
// Either gate failing renders StaticHeroFallback instead: a plain CSS
// radial-gradient blob, sized identically to the real canvas via the
// same `className`, so there is no layout shift between the fallback
// and the real canvas mounting -- gradient colours come from
// tailwind.config.ts's brand scale via Tailwind's arbitrary-value
// `theme()` function, not a hard-coded hex, per the work order's "no
// ad-hoc hex" constraint.

import { Suspense, lazy } from "react";

import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { useWebglSupported } from "@/hooks/useWebglSupported";
import { cn } from "@/lib/cn";

const HeroSceneCanvas = lazy(() => import("@/components/three/HeroSceneCanvas"));

export interface HeroSceneProps {
  className?: string;
}

function StaticHeroFallback({ className }: { className?: string | undefined }): JSX.Element {
  return (
    <div
      aria-hidden="true"
      data-testid="hero-scene-fallback"
      className={cn(
        "rounded-full opacity-90",
        "bg-[radial-gradient(circle_at_30%_30%,theme(colors.brand.300),theme(colors.brand.600)_70%)]",
        className,
      )}
    />
  );
}

/** Mounts the landing hero's 3D scene when motion + WebGL both allow it; a static gradient otherwise. */
export function HeroScene({ className }: HeroSceneProps): JSX.Element {
  const prefersReducedMotion = usePrefersReducedMotion();
  const webglSupported = useWebglSupported();

  if (prefersReducedMotion || !webglSupported) {
    return <StaticHeroFallback className={className} />;
  }

  return (
    <div aria-hidden="true" data-testid="hero-scene-canvas" className={className}>
      <Suspense fallback={<StaticHeroFallback className="h-full w-full" />}>
        <HeroSceneCanvas />
      </Suspense>
    </div>
  );
}
