// frontend/src/hooks/useIsLowEndDevice.ts
// AIRP -- low-end/mobile device heuristic (Section C audit finding,
// deferred from unit 9)
//
// HeroScene.tsx's capability gate previously checked only
// prefers-reduced-motion and WebGL context availability. Nearly every
// modern phone -- including genuinely low-end ones -- DOES support WebGL,
// so that gate let the full three.js/@react-three/fiber scene load and
// animate on exactly the hardware B10's own work order calls out as
// needing graceful degradation ("must degrade gracefully on
// low-end/mobile"). This hook adds the missing signal.
//
// Deliberately a heuristic, not a benchmark: there is no reliable,
// synchronous, cross-browser way to measure actual GPU capability before
// paint. Three independent, cheap signals are combined with OR, so any
// one of them alone is enough to treat the device as low-end:
//   1. navigator.hardwareConcurrency (logical CPU cores) -- broadly
//      supported.
//   2. navigator.deviceMemory (RAM in GB) -- Chrome/Edge only (absent on
//      Safari/Firefox), used only when present, never required.
//   3. A coarse (touch) primary pointer AND a phone-width viewport
//      together, as a stand-in for "this is a phone" -- a tablet or a
//      touchscreen laptop alone should not trip this; it takes both
//      signals together.
// The risk this heuristic accepts is asymmetric on purpose: a false
// negative (a genuinely low-end device this misses) degrades no worse
// than before this fix existed; a false positive (a capable device
// treated as low-end) costs nothing but a CSS gradient instead of the 3D
// hero. Erring toward the fallback is the safe direction.

import { useEffect, useState } from "react";

/** Devices reporting this many logical CPU cores or fewer are treated as low-end. */
const LOW_END_CORE_COUNT_THRESHOLD = 4;

/** Devices reporting this little RAM (GB) or less are treated as low-end (Chrome/Edge only -- see module docstring). */
const LOW_END_MEMORY_GB_THRESHOLD = 4;

/** Viewport at or below this width, combined with a coarse pointer, is treated as phone-class. */
const NARROW_VIEWPORT_MAX_WIDTH_PX = 480;

interface NavigatorWithDeviceMemory extends Navigator {
  /** Non-standard, Chrome/Edge-only Device Memory API -- absent everywhere else. */
  deviceMemory?: number;
}

function probeIsLowEndDevice(): boolean {
  if (typeof navigator === "undefined" || typeof window === "undefined") {
    return false;
  }

  const cores = navigator.hardwareConcurrency;
  if (typeof cores === "number" && cores > 0 && cores <= LOW_END_CORE_COUNT_THRESHOLD) {
    return true;
  }

  const memoryGb = (navigator as NavigatorWithDeviceMemory).deviceMemory;
  if (typeof memoryGb === "number" && memoryGb <= LOW_END_MEMORY_GB_THRESHOLD) {
    return true;
  }

  if (typeof window.matchMedia !== "function") {
    return false;
  }
  const isCoarsePointer = window.matchMedia("(pointer: coarse)").matches;
  const isNarrowViewport = window.matchMedia(
    `(max-width: ${NARROW_VIEWPORT_MAX_WIDTH_PX}px)`,
  ).matches;
  return isCoarsePointer && isNarrowViewport;
}

/** True when the current device looks low-end or phone-class enough that a heavy three.js scene should not be mounted. */
export function useIsLowEndDevice(): boolean {
  const [isLowEnd, setIsLowEnd] = useState(false);

  useEffect(() => {
    setIsLowEnd(probeIsLowEndDevice());
  }, []);

  return isLowEnd;
}
