// frontend/src/test/authApi.test.ts
// Tests for src/api/auth.ts (T-056): request shape (URL, method,
// credentials) and AuthApiError message extraction from both FastAPI
// error-body shapes (a plain string detail, and a Pydantic 422
// validation-error array).

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AuthApiError,
  confirmPasswordReset,
  loginUser,
  logoutUser,
  registerUser,
  requestPasswordReset,
} from "@/api/auth";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const TOKEN_RESPONSE = {
  access_token: "jwt",
  token_type: "bearer",
  expires_in_minutes: 60,
  user: {
    id: "1",
    email: "a@example.com",
    display_name: null,
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
  },
};

describe("registerUser", () => {
  it("posts to /register with credentials included", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, TOKEN_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await registerUser({ email: "a@example.com", password: "password123" });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/register");
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include");
  });

  it("sends null display_name when none is given", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, TOKEN_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await registerUser({ email: "a@example.com", password: "password123" });

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string) as { display_name: unknown };
    expect(body.display_name).toBeNull();
  });

  it("throws AuthApiError with the backend's detail string on 409", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(409, { detail: "A user with this email already exists" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      registerUser({ email: "dup@example.com", password: "password123" }),
    ).rejects.toThrow("A user with this email already exists");
  });
});

describe("loginUser", () => {
  it("throws AuthApiError with a generic message for a malformed error body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("not json", { status: 500 }));
    vi.stubGlobal("fetch", fetchMock);

    const error = await loginUser({ email: "a@example.com", password: "x" }).catch(
      (caught: unknown) => caught,
    );
    expect(error).toBeInstanceOf(AuthApiError);
    expect((error as AuthApiError).message).toBe("Something went wrong. Please try again.");
  });

  it("extracts the first message from a 422 validation-error array", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse(422, { detail: [{ msg: "value is not a valid email address" }] }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(loginUser({ email: "bad", password: "x" })).rejects.toThrow(
      "value is not a valid email address",
    );
  });
});

describe("logoutUser", () => {
  it("posts to /logout and resolves on a 204 with no body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(logoutUser()).resolves.toBeUndefined();
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/logout");
    expect(options.credentials).toBe("include");
  });
});

// (B6) Password reset.

describe("requestPasswordReset", () => {
  it("posts to /password-reset/request with credentials included", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { message: "generic message" }));
    vi.stubGlobal("fetch", fetchMock);

    await requestPasswordReset({ email: "a@example.com" });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/password-reset/request");
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include");
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body).toEqual({ email: "a@example.com" });
  });

  it("resolves with the backend's generic message regardless of the email", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, {
        message: "If an account exists for that email, a password reset link has been sent.",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await requestPasswordReset({ email: "nobody@example.com" });

    expect(result.message).toBe(
      "If an account exists for that email, a password reset link has been sent.",
    );
  });
});

describe("confirmPasswordReset", () => {
  it("posts to /password-reset/confirm with token and new_password (snake_case)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { message: "Your password has been reset." }));
    vi.stubGlobal("fetch", fetchMock);

    await confirmPasswordReset({ token: "raw-token", newPassword: "BrandNewPassw0rd!" });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/password-reset/confirm");
    expect(options.credentials).toBe("include");
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body).toEqual({ token: "raw-token", new_password: "BrandNewPassw0rd!" });
  });

  it("throws AuthApiError(400) for an invalid or expired token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(400, {
        detail: "This reset link is invalid or has expired. Please request a new one.",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    try {
      await confirmPasswordReset({ token: "stale-token", newPassword: "BrandNewPassw0rd!" });
      expect.unreachable("confirmPasswordReset should have thrown");
    } catch (error) {
      expect(error).toBeInstanceOf(AuthApiError);
      expect((error as AuthApiError).status).toBe(400);
      expect((error as AuthApiError).message).toBe(
        "This reset link is invalid or has expired. Please request a new one.",
      );
    }
  });
});
