// frontend/src/components/toast/ToastViewport.tsx
// AIRP -- Toast viewport (T-066)
//
// Mounted exactly once, in AppProviders.tsx (its own docstring already
// anticipates "adding a provider later (theme, auth, toaster)" for
// this exact purpose) -- every toast in the app, however it was
// triggered (a manual `toast.error(...)` call, or automatically via
// src/lib/queryClient.ts's global QueryCache/MutationCache onError),
// renders through this one always-present viewport rather than each
// page needing its own.
//
// `aria-live="polite"` on the container plus each Toast's own
// `role="status"`/`role="alert"` (see Toast.tsx) together follow the
// same pattern MDN recommends for a toast region: the container
// announces additions, individual toasts carry their own urgency.
// `pointer-events-none` on the container + `pointer-events-auto` on
// each card (Toast.tsx) means the empty space around stacked toasts
// never blocks clicks on whatever's underneath.

import { Toast } from "@/components/toast/Toast";
import { useToasts } from "@/hooks/useToasts";
import { cn } from "@/lib/cn";
import { toastStore } from "@/lib/toastStore";

/** Renders every active toast, stacked bottom-right on desktop and bottom-centre on mobile. */
export function ToastViewport(): JSX.Element {
  const toasts = useToasts();

  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      data-testid="toast-viewport"
      className={cn(
        "pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 p-4",
        "sm:items-end",
      )}
    >
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} onDismiss={toastStore.remove} />
      ))}
    </div>
  );
}
