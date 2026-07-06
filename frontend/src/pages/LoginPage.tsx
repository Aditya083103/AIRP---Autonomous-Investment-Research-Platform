// frontend/src/pages/LoginPage.tsx
// AIRP -- Login page (T-056)
//
// react-hook-form + zodResolver(loginSchema) for client-side validation
// (src/lib/validation/authSchemas.ts), useAuth().login for the actual
// POST /auth/login call. On success, navigates to wherever the visitor
// was headed before ProtectedRoute redirected them here (state.from),
// falling back to /dashboard for a direct visit to /login. On failure,
// the backend's error message (e.g. "Incorrect email or password") is
// shown as a form-level error via react-hook-form's "root" error slot,
// rather than attributed to a specific field -- login intentionally
// cannot say which of email/password was wrong (see
// backend/routers/auth.py's non-enumeration comment).

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useLocation, useNavigate } from "react-router-dom";

import { AuthApiError } from "@/api/auth";
import { AuthCard } from "@/components/auth/AuthCard";
import { Button, Input } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { toast } from "@/lib/toast";
import { loginSchema, type LoginFormValues } from "@/lib/validation/authSchemas";

interface LocationState {
  from?: { pathname: string };
}

export function LoginPage(): JSX.Element {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
  });

  const onSubmit = async (values: LoginFormValues): Promise<void> => {
    setFormError(null);
    try {
      await login(values);
      const state = location.state as LocationState | null;
      const redirectTo = state?.from?.pathname ?? "/dashboard";
      navigate(redirectTo, { replace: true });
    } catch (error) {
      const message =
        error instanceof AuthApiError ? error.message : "Could not log in. Please try again.";
      setFormError(message);
      // T-066: login/register call useAuth() directly rather than going
      // through a React Query mutation, so src/lib/queryClient.ts's
      // global MutationCache.onError toast (see that file's docstring)
      // does not cover this catch block -- it has to fire explicitly
      // here, same as RegisterPage's and AnalysisPage's identical
      // try/catch shape.
      toast.error(message);
    }
  };

  return (
    <AuthCard
      title="Log in"
      subtitle="Pick up where you left off with your investment committee."
      footer={{ prompt: "New to AIRP?", linkLabel: "Create an account", linkTo: "/register" }}
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
          label="Password"
          type="password"
          autoComplete="current-password"
          {...register("password")}
          {...(errors.password?.message ? { error: errors.password.message } : {})}
        />

        {formError ? (
          <p role="alert" className="text-sm text-verdict-sell">
            {formError}
          </p>
        ) : null}

        <Button type="submit" isLoading={isSubmitting} fullWidth>
          Log in
        </Button>
      </form>
    </AuthCard>
  );
}
