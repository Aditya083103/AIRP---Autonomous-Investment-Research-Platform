// frontend/src/lib/validation/authSchemas.ts
// AIRP -- Auth form schemas (T-056)
//
// zod schemas for react-hook-form's zodResolver. Password length bounds
// (8-72) are copied from backend.models.schemas' UserRegisterRequest
// (_MIN_PASSWORD_LENGTH / _MAX_PASSWORD_LENGTH) so a form error appears
// before a round trip to the backend, not just after a 422 response --
// see src/api/auth.ts's parseErrorDetail for the fallback path if a
// request somehow bypasses this (it shouldn't, but the backend is the
// source of truth either way).

import { z } from "zod";

// Mirrors backend.models.schemas._MIN_PASSWORD_LENGTH / _MAX_PASSWORD_LENGTH.
const PASSWORD_MIN_LENGTH = 8;
const PASSWORD_MAX_LENGTH = 72;
const DISPLAY_NAME_MAX_LENGTH = 200;

const emailField = z.string().min(1, "Email is required.").email("Enter a valid email address.");

export const loginSchema = z.object({
  email: emailField,
  password: z.string().min(1, "Password is required."),
});

export type LoginFormValues = z.infer<typeof loginSchema>;

export const registerSchema = z
  .object({
    email: emailField,
    displayName: z
      .string()
      .max(
        DISPLAY_NAME_MAX_LENGTH,
        `Display name must be ${DISPLAY_NAME_MAX_LENGTH} characters or fewer.`,
      )
      .optional(),
    password: z
      .string()
      .min(PASSWORD_MIN_LENGTH, `Password must be at least ${PASSWORD_MIN_LENGTH} characters.`)
      .max(PASSWORD_MAX_LENGTH, `Password must be ${PASSWORD_MAX_LENGTH} characters or fewer.`)
      .refine((value) => value.trim().length > 0, "Password must not be blank."),
    confirmPassword: z.string().min(1, "Confirm your password."),
  })
  .refine((values) => values.password === values.confirmPassword, {
    message: "Passwords do not match.",
    path: ["confirmPassword"],
  });

export type RegisterFormValues = z.infer<typeof registerSchema>;
