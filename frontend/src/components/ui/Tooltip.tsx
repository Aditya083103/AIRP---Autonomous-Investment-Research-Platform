// frontend/src/components/ui/Tooltip.tsx
// Design-system primitive (T-054). A lightweight hover/focus tooltip for
// short clarifying text (e.g. explaining what "conviction score" means
// next to the Portfolio Manager's verdict). Deliberately CSS-only
// positioning rather than a floating-ui/popper dependency -- AIRP's
// tooltips are short, static-content hints, not complex collision-aware
// popovers, so the extra dependency weight isn't justified yet.

import {
  cloneElement,
  useId,
  useState,
  type FocusEventHandler,
  type MouseEventHandler,
  type ReactElement,
  type ReactNode,
} from "react";

import { cn } from "@/lib/cn";

export type TooltipPlacement = "top" | "bottom" | "left" | "right";

/** The subset of props Tooltip injects into its trigger via cloneElement. */
interface TooltipTriggerProps {
  "aria-describedby"?: string;
  onMouseEnter?: MouseEventHandler;
  onMouseLeave?: MouseEventHandler;
  onFocus?: FocusEventHandler;
  onBlur?: FocusEventHandler;
}

export interface TooltipProps {
  /** The tooltip's text content. */
  content: ReactNode;
  /** A single element that triggers the tooltip on hover/focus. */
  children: ReactElement<TooltipTriggerProps>;
  /** Which side of the trigger the tooltip appears on. Defaults to "top". */
  placement?: TooltipPlacement;
}

const PLACEMENT_CLASSES: Record<TooltipPlacement, string> = {
  top: "bottom-full left-1/2 mb-2 -translate-x-1/2",
  bottom: "top-full left-1/2 mt-2 -translate-x-1/2",
  left: "right-full top-1/2 mr-2 -translate-y-1/2",
  right: "left-full top-1/2 ml-2 -translate-y-1/2",
};

/**
 * Wraps a single trigger element and shows a small text tooltip on hover
 * or keyboard focus. The trigger is described via `aria-describedby`, so
 * screen readers announce the tooltip content without it needing to be
 * focusable itself.
 */
export function Tooltip({ content, children, placement = "top" }: TooltipProps): JSX.Element {
  const [isVisible, setIsVisible] = useState(false);
  const tooltipId = useId();

  function show(): void {
    setIsVisible(true);
  }

  function hide(): void {
    setIsVisible(false);
  }

  const trigger = cloneElement(children, {
    "aria-describedby": tooltipId,
    onMouseEnter: show,
    onMouseLeave: hide,
    onFocus: show,
    onBlur: hide,
  });

  return (
    <span className="relative inline-flex">
      {trigger}
      <span
        id={tooltipId}
        role="tooltip"
        className={cn(
          "absolute z-10 whitespace-nowrap rounded-md bg-ink px-2.5 py-1.5 text-xs",
          "font-medium text-white shadow-card transition-opacity duration-150",
          PLACEMENT_CLASSES[placement],
          isVisible ? "visible opacity-100" : "invisible opacity-0",
        )}
      >
        {content}
      </span>
    </span>
  );
}
