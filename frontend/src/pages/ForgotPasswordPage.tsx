// frontend/src/pages/ForgotPasswordPage.tsx
// AIRP -- Forgot password page (B6)
//
// The first step of the "forgot password" flow: collects an email and
// calls POST /auth/password-reset/request (src/api/auth.ts's
// requestPasswordReset). Deliberately does NOT branch on the response
// -- backend/routers/auth.py always returns the same 200/generic
// message whether or not the email matched a real account (the
// anti-enumeration guarantee that endpoint's own docstring explains),
// so this page shows the SAME success state either way rather than
// giving a form a network error to react differently to. A network
// failure (the request itself never reaching the backend) is the only
// case that surfaces as a form error instead.
//
// Reached from LoginPage's new "Forgot password?" link; the confirm
// step (ResetPasswordPage) is reached separately, via the link the
// backend emails/logs, not by navigating from this page.

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { AuthApiError, requestPasswordReset } from "@/api/auth";
import { AuthCard } from "@/components/auth/AuthCard";
import { Button, Input } from "@/components/ui";
import { forgotPasswordSchema, type ForgotPasswordFormValues } from "@/lib/validation/authSchemas";

export function ForgotPasswordPage(): JSX.Element {
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitted, setIsSubmitted] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ForgotPasswordFormValues>({
    resolver: zodResolver(forgotPasswordSchema),
  });

  const onSubmit = async (values: ForgotPasswordFormValues): Promise<void> => {
    setFormError(null);
    try {
      await requestPasswordReset({ email: values.email });
      setIsSubmitted(true);
    } catch (error) {
      // Reached only for a genuine request failure (network error, the
      // backend unreachable, a malformed request) -- NOT for "no such
      // account", which the backend deliberately answers with the same
      // 200 success response every other email gets.
      const message =
        error instanceof AuthApiError
          ? error.message
          : "Could not send the reset link. Please try again.";
      setFormError(message);
    }
  };

  if (isSubmitted) {
    return (
      <AuthCard
        title="Check your email"
        subtitle="If an account exists for that email, we've sent a link to reset your password."
        footer={{ prompt: "Remembered it after all?", linkLabel: "Log in", linkTo: "/login" }}
      >
        <p className="text-sm text-muted">
          The link expires soon and can only be used once. If it does not arrive in a few minutes,
          check your spam folder or try again.
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Forgot your password?"
      subtitle="Enter your email and we'll send you a link to reset it."
      footer={{ prompt: "Remembered it after all?", linkLabel: "Log in", linkTo: "/login" }}
    >
      <form className="flex flex-col gap-4" onSubmit={handleSubmit(onSubmit)} noValidate>
        <Input
          label="Email"
          type="email"
          autoComplete="email"
          {...register("email")}
          {...(errors.email?.message ? { error: errors.email.message } : {})}
        />

        {formError ? (
          <p role="alert" className="text-sm text-verdict-sell">
            {formError}
          </p>
        ) : null}

        <Button type="submit" isLoading={isSubmitting} fullWidth>
          Send reset link
        </Button>
      </form>
    </AuthCard>
  );
}
