// frontend/src/hooks/useToasts.ts
// AIRP -- useToasts hook (T-066)
//
// Thin useSyncExternalStore wrapper around toastStore.ts -- the
// React-facing half of the store/hook split, kept separate from
// lib/toastStore.ts itself so that store module stays framework-free
// and callable from non-component code (see that file's docstring).
// ToastViewport.tsx is the only consumer today, but any component
// could subscribe the same way.

import { useSyncExternalStore } from "react";

import { toastStore, type ToastRecord } from "@/lib/toastStore";

export function useToasts(): readonly ToastRecord[] {
  return useSyncExternalStore(toastStore.subscribe, toastStore.getSnapshot, toastStore.getSnapshot);
}
