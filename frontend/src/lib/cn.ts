// frontend/src/lib/cn.ts
// Class-name merge helper for the design system: clsx resolves conditional
// class arrays/objects, tailwind-merge then de-duplicates conflicting
// Tailwind utilities (e.g. "px-2 px-4" -> "px-4"). Every component composes
// classes through this so prop-driven overrides win predictably.

import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
