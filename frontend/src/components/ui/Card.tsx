// frontend/src/components/ui/Card.tsx
// Design-system primitive (T-054). The surface container used everywhere
// content needs visual grouping: dashboard tiles, the memo viewer, agent
// result panels. Matches the `rounded-card` / `shadow-card` tokens already
// used ad hoc in HomePage.tsx (T-053) -- this formalises that pattern into
// a reusable component with an explicit header/body/footer composition API
// instead of every page hand-rolling the same border/shadow classes.

import { type ComponentPropsWithoutRef } from "react";

import { cn } from "@/lib/cn";

export interface CardProps extends ComponentPropsWithoutRef<"div"> {
  /** Removes the default padding, for cards that manage their own inner spacing. */
  noPadding?: boolean;
}

/** The base bordered, shadowed surface every Card.* part renders inside. */
function CardRoot({ noPadding = false, className, children, ...rest }: CardProps): JSX.Element {
  return (
    <div
      className={cn(
        "rounded-card border border-line bg-surface shadow-card",
        !noPadding && "p-6",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export type CardHeaderProps = ComponentPropsWithoutRef<"div">;

/** Title/description region. Place at the top of a Card. */
function CardHeader({ className, children, ...rest }: CardHeaderProps): JSX.Element {
  return (
    <div className={cn("mb-4 flex items-start justify-between gap-3", className)} {...rest}>
      {children}
    </div>
  );
}

export type CardTitleProps = ComponentPropsWithoutRef<"h3">;

/**
 * The Card's heading. Renders as an h3 -- adjust the surrounding page's
 * heading levels accordingly.
 */
function CardTitle({ className, children, ...rest }: CardTitleProps): JSX.Element {
  return (
    <h3 className={cn("text-sm font-semibold text-ink", className)} {...rest}>
      {children}
    </h3>
  );
}

export type CardDescriptionProps = ComponentPropsWithoutRef<"p">;

/** Secondary text under CardTitle. */
function CardDescription({ className, children, ...rest }: CardDescriptionProps): JSX.Element {
  return (
    <p className={cn("text-sm leading-relaxed text-muted", className)} {...rest}>
      {children}
    </p>
  );
}

export type CardFooterProps = ComponentPropsWithoutRef<"div">;

/** Action row pinned to the bottom of a Card (e.g. buttons). */
function CardFooter({ className, children, ...rest }: CardFooterProps): JSX.Element {
  const footerClassName = cn(
    "mt-4 flex items-center justify-end gap-3 border-t border-line pt-4",
    className,
  );
  return (
    <div className={footerClassName} {...rest}>
      {children}
    </div>
  );
}

/**
 * AIRP's surface container, with a compound-component API:
 *
 * ```tsx
 * <Card>
 *   <Card.Header>
 *     <Card.Title>Fundamental Analysis</Card.Title>
 *     <Badge tone="buy">BUY</Badge>
 *   </Card.Header>
 *   <Card.Description>Revenue growth accelerating QoQ.</Card.Description>
 *   <Card.Footer>
 *     <Button size="sm">View detail</Button>
 *   </Card.Footer>
 * </Card>
 * ```
 */
export const Card = Object.assign(CardRoot, {
  Header: CardHeader,
  Title: CardTitle,
  Description: CardDescription,
  Footer: CardFooter,
});
