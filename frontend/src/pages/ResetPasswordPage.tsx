// frontend/src/pages/ResetPasswordPage.tsx
// AIRP -- Reset password page (B6)
//
// The second step of the "forgot password" flow, reached via the link
// backend/routers/auth.py emails/logs (?token=<raw token>). Collects a
// new password (with confirm-match, src/lib/validation/authSchemas.ts's
// resetPasswordSchema) and calls POST /auth/password-reset/confirm
// (src/api/auth.ts's confirmPasswordReset). On success, redirects to
// /login with a success toast -- exactly the work order's specified
// behaviour, not back into the app directly, since the person is not
// authenticated by this flow (POST .../confirm returns no token; they
// still need to log in with the new password).
//
// A missing/empty `?token=` (someone navigating here directly, or a
// truncated/mangled link) short-circuits to an error state before any
// form is even shown -- there is nothing a submitted form could do
// without a token.

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate, useSearchParams } from "react-router-dom";

import { AuthApiError, confirmPasswordReset } from "@/api/auth";
import { AuthCard } from "@/components/auth/AuthCard";
import { Button, Input } from "@/components/ui";
import { toast } from "@/lib/toast";
import { resetPasswordSchema, type ResetPasswordFormValues } from "@/lib/validation/authSchemas";

export function ResetPasswordPage(): JSX.Element {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");
  const navigate = useNavigate();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ResetPasswordFormValues>({
    resolver: zodResolver(resetPasswordSchema),
  });

  const onSubmit = async (values: ResetPasswordFormValues): Promise<void> => {
    if (!token) {
      return;
    }
    setFormError(null);
    try {
      await confirmPasswordReset({ token, newPassword: values.newPassword });
      toast.success("Your password has been reset. Please log in with your new password.");
      navigate("/login", { replace: true });
    } catch (error) {
      const message =
        error instanceof AuthApiError
          ? error.message
          : "Could not reset your password. Please try again.";
      setFormError(message);
    }
  };

  if (!token) {
    return (
      <AuthCard
        title="Invalid reset link"
        subtitle="This password reset link is missing its token -- it may have been copied incorrectly."
        footer={{
          prompt: "Need a new link?",
          linkLabel: "Request a password reset",
          linkTo: "/forgot-password",
        }}
      >
        <p className="text-sm text-muted">
          Open the link from your email again, or request a new one if it has expired.
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Reset your password"
      subtitle="Choose a new password for your account."
      footer={{ prompt: "Remembered it after all?", linkLabel: "Log in", linkTo: "/login" }}
    >
      <form className="flex flex-col gap-4" onSubmit={handleSubmit(onSubmit)} noValidate>
        <Input
          label="New password"
          type="password"
          autoComplete="new-password"
          {...register("newPassword")}
          {...(errors.newPassword?.message ? { error: errors.newPassword.message } : {})}
        />
        <Input
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          {...register("confirmNewPassword")}
          {...(errors.confirmNewPassword?.message
            ? { error: errors.confirmNewPassword.message }
            : {})}
        />

        {formError ? (
          <p role="alert" className="text-sm text-verdict-sell">
            {formError}
          </p>
        ) : null}

        <Button type="submit" isLoading={isSubmitting} fullWidth>
          Reset password
        </Button>
      </form>
    </AuthCard>
  );
}
