// frontend/src/pages/RegisterPage.tsx
// AIRP -- Register page (T-056)
//
// react-hook-form + zodResolver(registerSchema) (password length,
// confirm-password match -- see src/lib/validation/authSchemas.ts).
// backend/routers/auth.py's POST /auth/register immediately returns a
// token (a new account is authenticated on the spot, no separate login
// step), so a successful submit here goes straight to /dashboard, same
// as a successful login.

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";

import { AuthApiError } from "@/api/auth";
import { AuthCard } from "@/components/auth/AuthCard";
import { Button, Input } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { toast } from "@/lib/toast";
import { registerSchema, type RegisterFormValues } from "@/lib/validation/authSchemas";

export function RegisterPage(): JSX.Element {
  const { register: registerAccount } = useAuth();
  const navigate = useNavigate();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
  });

  const onSubmit = async (values: RegisterFormValues): Promise<void> => {
    setFormError(null);
    try {
      await registerAccount({
        email: values.email,
        password: values.password,
        displayName: values.displayName,
      });
      navigate("/dashboard", { replace: true });
    } catch (error) {
      const message =
        error instanceof AuthApiError
          ? error.message
          : "Could not create your account. Please try again.";
      setFormError(message);
      // T-066: see LoginPage.tsx's identical catch block for why this
      // toast call has to be explicit here rather than coming from
      // src/lib/queryClient.ts's global mutation-error handler.
      toast.error(message);
    }
  };

  return (
    <AuthCard
      title="Create an account"
      subtitle="Join the committee -- register to run your first analysis."
      footer={{ prompt: "Already have an account?", linkLabel: "Log in", linkTo: "/login" }}
    >
      <form className="flex flex-col gap-4" onSubmit={handleSubmit(onSubmit)} noValidate>
        <Input
          label="Email"
          type="email"
          autoComplete="email"
          {...register("email")}
          {...(errors.email?.message ? { error: errors.email.message } : {})}
        />
        <Input
          label="Display name"
          hint="Optional -- shown on your dashboard."
          autoComplete="name"
          {...register("displayName")}
          {...(errors.displayName?.message ? { error: errors.displayName.message } : {})}
        />
        <Input
          label="Password"
          type="password"
          autoComplete="new-password"
          {...register("password")}
          {...(errors.password?.message ? { error: errors.password.message } : {})}
        />
        <Input
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          {...register("confirmPassword")}
          {...(errors.confirmPassword?.message ? { error: errors.confirmPassword.message } : {})}
        />

        {formError ? (
          <p role="alert" className="text-sm text-verdict-sell">
            {formError}
          </p>
        ) : null}

        <Button type="submit" isLoading={isSubmitting} fullWidth>
          Create account
        </Button>
      </form>
    </AuthCard>
  );
}
