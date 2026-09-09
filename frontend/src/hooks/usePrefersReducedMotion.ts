// frontend/src/hooks/usePrefersReducedMotion.ts
// AIRP -- prefers-reduced-motion detection (B10)
//
// Every framer-motion / 3D primitive B10 adds (Reveal, AnimatedNumber,
// PageTransition, HeroScene, TiltCard) reads this hook and renders its
// static, final-state equivalent instead of animating when it reports
// true -- the work order's explicit accessibility/performance
// constraint ("honor prefers-reduced-motion: disable heavy motion/3D").
// Centralised here rather than duplicated per-component so every
// consumer stays in sync with a single source of truth, and so a test
// can flip the media query once (via window.matchMedia) and assert
// every consumer responds the same way.

import { useEffect, useState } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

function getInitialPreference(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia(QUERY).matches;
}

/** True when the visitor's OS/browser requests reduced motion. Reactive to live changes. */
export function usePrefersReducedMotion(): boolean {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(getInitialPreference);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return undefined;
    }
    const mediaQueryList = window.matchMedia(QUERY);
    const handleChange = (event: MediaQueryListEvent): void => {
      setPrefersReducedMotion(event.matches);
    };

    if (typeof mediaQueryList.addEventListener === "function") {
      mediaQueryList.addEventListener("change", handleChange);
      return () => mediaQueryList.removeEventListener("change", handleChange);
    }
    // Safari < 14 fallback -- addListener/removeListener predate the
    // standard EventTarget API on MediaQueryList.
    mediaQueryList.addListener(handleChange);
    return () => mediaQueryList.removeListener(handleChange);
  }, []);

  return prefersReducedMotion;
}
