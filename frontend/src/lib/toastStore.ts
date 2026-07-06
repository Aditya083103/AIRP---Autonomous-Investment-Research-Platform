// frontend/src/lib/toastStore.ts
// AIRP -- Toast store (T-066)
//
// A minimal external store (subscribe/getSnapshot, the same shape
// React's own `useSyncExternalStore` expects) rather than a React
// context, because the whole point of this task's "API errors show a
// toast" criterion is firing a toast from places that are NOT inside
// the React tree at the moment the error happens -- most importantly
// src/lib/queryClient.ts's QueryCache/MutationCache `onError`
// callbacks, which run as plain TanStack Query internals with no
// component instance, hook, or context available to them at all. A
// module-level store that any plain function can call `.add()` on,
// and that a mounted <ToastViewport> subscribes to for re-renders, is
// the standard way to bridge that gap without threading a dispatch
// function through non-React code.
//
// No toast library (react-hot-toast, sonner, etc.) is a project
// dependency, and none of the existing UI primitives needed one either
// (Tooltip.tsx and CompanyAutocomplete.tsx are both hand-rolled for the
// same "no npm install against an unreachable registry" reason) -- this
// keeps that pattern.

export type ToastTone = "success" | "error" | "info";

export interface ToastRecord {
  readonly id: string;
  readonly tone: ToastTone;
  readonly message: string;
}

type Listener = () => void;

let toasts: readonly ToastRecord[] = [];
const listeners = new Set<Listener>();
let nextId = 0;

function emit(): void {
  listeners.forEach((listener) => listener());
}

function add(tone: ToastTone, message: string): string {
  const id = `toast-${(nextId += 1)}`;
  toasts = [...toasts, { id, tone, message }];
  emit();
  return id;
}

function remove(id: string): void {
  const next = toasts.filter((toast) => toast.id !== id);
  if (next.length !== toasts.length) {
    toasts = next;
    emit();
  }
}

/** Removes every toast. Exists mainly so tests can reset shared module state between cases. */
function clear(): void {
  toasts = [];
  emit();
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): readonly ToastRecord[] {
  return toasts;
}

export const toastStore = { add, remove, clear, subscribe, getSnapshot };
