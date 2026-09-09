// frontend/src/hooks/useWebglSupported.ts
// AIRP -- WebGL capability probe (B10)
//
// HeroScene.tsx (the landing page's lazy-loaded react-three-fiber hero)
// gates on this before ever import()-ing three.js/@react-three/fiber --
// mounting a WebGL canvas on a device/browser that cannot create a
// context would either throw or render a blank black box, and the work
// order is explicit that 3D "must degrade gracefully on low-end/mobile."
// A cheap, synchronous `canvas.getContext("webgl")` probe answers that
// directly. It also, as a side effect, keeps three.js out of every
// component test for free: jsdom's canvas has no WebGL backend, so
// `getContext("webgl")` returns null there -- this hook reports `false`
// under Vitest without any test needing to mock three.js at all.

import { useEffect, useState } from "react";

function probeWebglSupport(): boolean {
  if (typeof document === "undefined") {
    return false;
  }
  try {
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
    return context !== null;
  } catch {
    return false;
  }
}

/** True when the current browser/device can actually create a WebGL context. */
export function useWebglSupported(): boolean {
  const [supported, setSupported] = useState(false);

  useEffect(() => {
    setSupported(probeWebglSupport());
  }, []);

  return supported;
}
