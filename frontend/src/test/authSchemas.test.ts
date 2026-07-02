// frontend/src/test/authSchemas.test.ts
// Tests for src/lib/validation/authSchemas.ts (T-056): pure zod logic,
// no rendering required.

import { describe, expect, it } from "vitest";

import { loginSchema, registerSchema } from "@/lib/validation/authSchemas";

describe("loginSchema", () => {
  it("accepts a valid email and non-empty password", () => {
    const result = loginSchema.safeParse({ email: "a@example.com", password: "anything" });
    expect(result.success).toBe(true);
  });

  it("rejects an invalid email", () => {
    const result = loginSchema.safeParse({ email: "not-an-email", password: "anything" });
    expect(result.success).toBe(false);
  });

  it("rejects an empty password", () => {
    const result = loginSchema.safeParse({ email: "a@example.com", password: "" });
    expect(result.success).toBe(false);
  });
});

describe("registerSchema", () => {
  const validBase = {
    email: "a@example.com",
    password: "correct-horse-battery",
    confirmPassword: "correct-horse-battery",
  };

  it("accepts matching passwords of valid length", () => {
    const result = registerSchema.safeParse(validBase);
    expect(result.success).toBe(true);
  });

  it("accepts an optional display name", () => {
    const result = registerSchema.safeParse({ ...validBase, displayName: "Aditya" });
    expect(result.success).toBe(true);
  });

  it("rejects mismatched passwords, attributed to confirmPassword", () => {
    const result = registerSchema.safeParse({
      ...validBase,
      confirmPassword: "something-else",
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0]?.path).toContain("confirmPassword");
    }
  });

  it("rejects a password shorter than 8 characters", () => {
    const result = registerSchema.safeParse({
      ...validBase,
      password: "short1",
      confirmPassword: "short1",
    });
    expect(result.success).toBe(false);
  });

  it("rejects a password longer than 72 characters", () => {
    const tooLong = "a".repeat(73);
    const result = registerSchema.safeParse({
      ...validBase,
      password: tooLong,
      confirmPassword: tooLong,
    });
    expect(result.success).toBe(false);
  });

  it("rejects a whitespace-only password", () => {
    const blank = " ".repeat(10);
    const result = registerSchema.safeParse({
      ...validBase,
      password: blank,
      confirmPassword: blank,
    });
    expect(result.success).toBe(false);
  });
});
