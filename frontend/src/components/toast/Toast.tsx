// frontend/src/components/toast/Toast.tsx
// AIRP -- Single toast card (T-066)
//
// Renders one ToastRecord (src/lib/toastStore.ts) as a dismissible
// card: auto-dismisses after AUTO_DISMISS_MS, or immediately on a
// manual close-button click -- same "hover doesn't need to pause the
// timer" simplicity MemoToolbar.tsx's own copy-feedback flash already
// settled for (see that component's COPY_FEEDBACK_DURATION_MS), not a
// gap, just not over-built for what is fundamentally a "we told you,
// move on" notification rather than something the user must act on
// before it disappears -- the underlying inline error/empty states this
// task also adds are what stays on screen for as long as the problem
// does.
//
// `role="alert"` (assertive) for error tone -- these fire from a
// failed request the user is actively waiting on and should be
// announced immediately. `role="status"` (polite) for success/info --
// announced without interrupting whatever the screen reader is already
// reading. Same tone-drives-urgency split src/api DebateMessageCard.tsx
// uses for its own status Badge tones, applied to ARIA role instead of
// colour.

import { useEffect } from "react";

import { cn } from "@/lib/cn";
import { type ToastRecord } from "@/lib/toastStore";

const AUTO_DISMISS_MS = 6000;

const TONE_CLASSES: Record<ToastRecord["tone"], string> = {
  success: "border-verdict-buy/30 bg-surface text-ink",
  error: "border-verdict-sell/30 bg-surface text-ink",
  info: "border-line bg-surface text-ink",
};

const TONE_ACCENT_CLASSES: Record<ToastRecord["tone"], string> = {
  success: "bg-verdict-buy",
  error: "bg-verdict-sell",
  info: "bg-brand-500",
};

export interface ToastProps {
  toast: ToastRecord;
  onDismiss: (id: string) => void;
}

function CloseIcon(): JSX.Element {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4" aria-hidden="true">
      <path
        d="M5 5l10 10M15 5L5 15"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** One dismissible toast card. Auto-dismisses after 6s, or immediately via its close button. */
export function Toast({ toast, onDismiss }: ToastProps): JSX.Element {
  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(toast.id), AUTO_DISMISS_MS);
    return () => window.clearTimeout(timer);
  }, [toast.id, onDismiss]);

  return (
    <div
      role={toast.tone === "error" ? "alert" : "status"}
      className={cn(
        "pointer-events-auto relative flex w-full max-w-sm items-start gap-3 overflow-hidden",
        "rounded-card border py-3 pl-4 pr-3 shadow-card",
        TONE_CLASSES[toast.tone],
      )}
      data-testid="toast"
      data-tone={toast.tone}
    >
      <span
        aria-hidden="true"
        className={cn("absolute inset-y-0 left-0 w-1", TONE_ACCENT_CLASSES[toast.tone])}
      />
      <p className="flex-1 text-sm leading-relaxed">{toast.message}</p>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss notification"
        className={cn(
          "shrink-0 rounded-full p-1 text-muted transition-colors hover:bg-canvas",
          "hover:text-ink focus-visible:outline-none focus-visible:ring-2",
          "focus-visible:ring-brand-500",
        )}
      >
        <CloseIcon />
      </button>
    </div>
  );
}
