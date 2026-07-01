// frontend/src/components/ui/Modal.tsx
// Design-system primitive (T-054). A dialog overlay for confirmations
// (e.g. "delete this analysis?"), the document-upload flow, and any other
// flow that needs to interrupt the page. Deliberately does not use
// createPortal: AIRP has no nested-overlay or z-index-stacking-context
// requirement that needs it yet, and rendering in normal DOM flow keeps
// this component trivially testable with React Testing Library (no portal
// container setup needed in tests).

import { useEffect, useId, useRef, type MouseEvent, type ReactNode } from "react";

import { cn } from "@/lib/cn";

export type ModalSize = "sm" | "md" | "lg";

export interface ModalProps {
  /** Controls whether the modal is rendered at all. */
  isOpen: boolean;
  /** Called when the user requests to close: Escape key, backdrop click, or close button. */
  onClose: () => void;
  /** Dialog heading, also used as the accessible name via aria-labelledby. */
  title: string;
  /** Dialog body content. */
  children: ReactNode;
  /** Optional footer content, typically action buttons. */
  footer?: ReactNode;
  /** Max-width of the dialog panel. Defaults to "md". */
  size?: ModalSize;
}

const SIZE_CLASSES: Record<ModalSize, string> = {
  sm: "max-w-sm",
  md: "max-w-lg",
  lg: "max-w-2xl",
};

/**
 * A centred dialog with a dismissible backdrop. Closes on Escape, on
 * backdrop click, and via the built-in close button -- all three call the
 * same `onClose`, so the caller only needs one handler.
 */
export function Modal({
  isOpen,
  onClose,
  title,
  children,
  footer,
  size = "md",
}: ModalProps): JSX.Element | null {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        onClose();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    panelRef.current?.focus();

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) {
    return null;
  }

  function handleBackdropClick(event: MouseEvent<HTMLDivElement>): void {
    if (event.target === event.currentTarget) {
      onClose();
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 p-4"
      onClick={handleBackdropClick}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cn(
          "w-full rounded-card border border-line bg-surface p-6 shadow-card focus:outline-none",
          SIZE_CLASSES[size],
        )}
      >
        <div className="flex items-start justify-between gap-4">
          <h2 id={titleId} className="text-lg font-semibold text-ink">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className={cn(
              "shrink-0 rounded-full p-1 text-muted transition-colors hover:bg-canvas",
              "hover:text-ink focus-visible:outline-none focus-visible:ring-2",
              "focus-visible:ring-brand-500",
            )}
          >
            <CloseIcon />
          </button>
        </div>

        <div className="mt-4 text-sm leading-relaxed text-ink">{children}</div>

        {footer && <div className="mt-6 flex items-center justify-end gap-3">{footer}</div>}
      </div>
    </div>
  );
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
