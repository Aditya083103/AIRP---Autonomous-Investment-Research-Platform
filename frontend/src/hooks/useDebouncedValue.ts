// frontend/src/hooks/useDebouncedValue.ts
// AIRP -- Generic debounce hook (B5)
//
// Returns `value`, but only after it has stopped changing for
// `delayMs` -- the standard "wait for the person to pause typing
// before firing a network request" pattern, extracted here rather
// than inlined in CompanyAutocomplete.tsx so any future
// search-as-you-type input can reuse it without depending on a
// combobox-specific component. No debounce/throttle utility library
// is already a dependency of this project (see
// CompanyAutocomplete.tsx's own module docstring for why a new
// `npm install` is avoided throughout this codebase), so this is a
// plain ~10-line useEffect + useState implementation rather than a
// pulled-in package.

import { useEffect, useState } from "react";

/**
 * Returns a debounced copy of `value`: it only updates once `value`
 * has stayed the same for `delayMs` milliseconds. Every intermediate
 * value during a fast burst of changes (e.g. someone typing) is
 * discarded -- only the final, settled value is ever returned.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return (): void => window.clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
