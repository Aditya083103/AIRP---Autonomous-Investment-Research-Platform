// frontend/src/components/auth/AuthCard.tsx
// AIRP -- Shared auth-page shell (T-056)
//
// Centres a Card with a title, optional subtitle, and the form itself
// (children) -- the layout LoginPage and RegisterPage both use, kept in
// one place so the two pages differ only in their form fields and
// submit handler, not their surrounding chrome.

import { type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Card } from "@/components/ui";

interface AuthCardProps {
  title: string;
  subtitle: string;
  /** Rendered below the form -- e.g. "Already have an account? Log in". */
  footer?: {
    prompt: string;
    linkLabel: string;
    linkTo: string;
  };
  children: ReactNode;
}

export function AuthCard({ title, subtitle, footer, children }: AuthCardProps): JSX.Element {
  return (
    <div className="mx-auto flex max-w-md flex-col py-12">
      <p className="text-center font-mono text-xs uppercase tracking-[0.2em] text-brand-600">
        AIRP
      </p>
      <h1 className="mt-3 text-center font-display text-3xl font-semibold text-ink">{title}</h1>
      <p className="mt-2 text-center text-sm text-muted">{subtitle}</p>

      <Card className="mt-8">{children}</Card>

      {footer ? (
        <p className="mt-6 text-center text-sm text-muted">
          {footer.prompt}{" "}
          <Link to={footer.linkTo} className="font-medium text-brand-600 hover:text-brand-700">
            {footer.linkLabel}
          </Link>
        </p>
      ) : null}
    </div>
  );
}
