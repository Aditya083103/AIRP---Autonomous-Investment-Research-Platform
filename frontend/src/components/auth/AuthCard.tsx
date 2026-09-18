// frontend/src/components/auth/AuthCard.tsx
// AIRP -- Shared auth-page shell (T-056)
//
// Centres a Card with a title, optional subtitle, and the form itself
// (children) -- the layout LoginPage, RegisterPage, ForgotPasswordPage,
// and ResetPasswordPage all use, kept in one place so those pages differ
// only in their form fields and submit handler, not their surrounding
// chrome. Because of that, a single Reveal wrap here (B10) gives every
// auth page the same clean fade/rise-in entrance without touching any
// of the four pages individually.

import { type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Reveal } from "@/components/motion/Reveal";
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
    <Reveal className="mx-auto flex max-w-md flex-col py-12">
      <p className="text-center font-mono text-xs uppercase tracking-[0.2em] text-brand-300">
        AIRP
      </p>
      <h1 className="mt-3 text-center font-display text-3xl font-semibold text-ink">{title}</h1>
      <p className="mt-2 text-center text-sm text-muted">{subtitle}</p>

      <Card className="mt-8">{children}</Card>

      {footer ? (
        <p className="mt-6 text-center text-sm text-muted">
          {footer.prompt}{" "}
          <Link to={footer.linkTo} className="font-medium text-brand-300 hover:text-brand-200">
            {footer.linkLabel}
          </Link>
        </p>
      ) : null}
    </Reveal>
  );
}
