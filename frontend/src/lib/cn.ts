// frontend/src/lib/cn.ts
// Class-name merge helper for the design system: clsx resolves conditional
// class arrays/objects, tailwind-merge then de-duplicates conflicting
// Tailwind utilities (e.g. "px-2 px-4" -> "px-4"). Every component composes
// classes through this so prop-driven overrides win predictably.
//
// extendTailwindMerge (landing-page redesign): tailwind-merge ships its
// own default value scale per class group (e.g. shadow's is
// ""/inner/none plus its OWN built-in sm/md/lg/xl/2xl theme guess) --
// it does not read this project's tailwind.config.ts, so a project-only
// custom key like `shadow-card` or `rounded-card` (see that file's
// `boxShadow`/`borderRadius` extensions) is invisible to it by default
// and never gets de-duplicated against a same-group override
// (`shadow-none`, a different `rounded-*`, etc.) -- both classes would
// silently end up in the final string, with CSS's own cascade order
// (not the override's intent) deciding which one actually renders.
// Registering both custom keys here is what makes e.g.
// `cn("rounded-card border shadow-card p-6", "shadow-none")` correctly
// drop `shadow-card`, the same as it would for any built-in Tailwind
// value.

import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

const customTwMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      rounded: ["rounded-card"],
      shadow: ["shadow-card"],
    },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return customTwMerge(clsx(inputs));
}
