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

// Section C audit finding (deferred from unit 9, fixed here): Modal had no
// focus trap or focus restoration. A keyboard/screen-reader user could Tab
// straight out of an open dialog into the page behind it (a WCAG 2.4.3 /
// ARIA APG dialog-pattern violation -- the two things every modal dialog
// implementation is expected to do), and closing it left focus wherever it
// happened to be (usually back at the very start of the document, since
// focus had moved onto the dialog panel) instead of back on the control
// that opened it.
const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "textarea:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

/**
 * Focusable descendants of `container`, in DOM (tab) order, excluding
 * anything explicitly marked hidden.
 *
 * Deliberately does NOT use `element.offsetParent !== null` as a
 * "visually hidden" filter, despite that being the common pattern for
 * this kind of check: jsdom (this project's test environment) never runs
 * layout, so `offsetParent` reads `null` for every element regardless of
 * whether it is actually hidden -- that filter would silently treat this
 * modal's ENTIRE contents as non-focusable under test while working fine
 * in a real browser, exactly the kind of environment-specific gap this
 * whole audit exists to catch (confirmed the hard way: an earlier version
 * of this trap using that check made every one of this file's own
 * focus-trap tests below land on the dialog panel instead of its buttons,
 * despite the buttons being genuinely visible and tabbable in a real
 * browser). `hidden`/`aria-hidden="true"` are both explicit, DOM-attribute
 * signals that work identically in jsdom and a real browser, and cover
 * every case this component's own callers actually rely on.
 */
function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) => !element.hasAttribute("hidden") && element.getAttribute("aria-hidden") !== "true",
  );
}

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

    // Restored on close below -- so a keyboard user (or a screen reader)
    // lands back exactly where they were before the dialog interrupted
    // them, typically the button that opened it, rather than at whatever
    // element the browser's default focus algorithm happens to pick once
    // the dialog panel itself (which held focus) is removed from the DOM.
    const previouslyFocusedElement = document.activeElement as HTMLElement | null;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }

      const panel = panelRef.current;
      if (panel === null) {
        return;
      }
      const focusable = getFocusableElements(panel);
      if (focusable.length === 0) {
        // Nothing focusable inside (e.g. a body-only confirmation with no
        // footer buttons rendered yet) -- keep focus pinned to the panel
        // itself rather than letting Tab escape to the page behind it.
        event.preventDefault();
        panel.focus();
        return;
      }

      const first = focusable[0] as HTMLElement;
      const last = focusable[focusable.length - 1] as HTMLElement;
      const active = document.activeElement;
      // `active === panel` covers the moment right after opening, before
      // focus has ever moved into a child -- Tab/Shift+Tab from there
      // must still wrap within the dialog, not fall through to native
      // "next focusable element in the whole document" behaviour.
      const isTrapped = active !== null && panel.contains(active) && active !== panel;

      if (event.shiftKey) {
        if (!isTrapped || active === first) {
          event.preventDefault();
          last.focus();
        }
      } else if (!isTrapped || active === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    panelRef.current?.focus();

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocusedElement?.focus();
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
      // ISSUE 5: was `bg-ink/50` -- a translucent DARK scrim while `ink`
      // meant near-black (the light theme). `ink` is now the near-white
      // foreground colour, so that same class would veil the page in
      // translucent white instead of dimming it. A modal backdrop scrim
      // conventionally darkens the page in any theme, light or dark, so
      // this uses a plain black overlay rather than a semantic token
      // whose meaning just inverted.
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
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
