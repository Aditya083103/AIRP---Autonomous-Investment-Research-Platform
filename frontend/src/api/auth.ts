// frontend/src/api/auth.ts
// AIRP -- Auth API client (T-056)
//
// Thin fetch wrappers around POST /auth/register, POST /auth/login, and
// POST /auth/logout (backend/routers/auth.py). Every request is sent with
// `credentials: "include"` so the browser sends/receives the httpOnly
// cookie those endpoints set (see backend/routers/auth.py's T-056
// docstring) -- this is required even though the response body's
// access_token is what the app actually reads (see
// src/providers/AuthProvider.tsx for why the raw token still has to live
// in JS memory for src/hooks/useAnalysisStream.ts's WebSocket auth).

import { env } from "@/config/env";
import { type TokenResponse } from "@/types/auth";

/**
 * Thrown for any non-2xx response from an auth endpoint. `message` is
 * already a human-readable string suitable for display directly in a
 * form (see parseErrorDetail below) -- callers never need to inspect
 * `status` to decide what to show, only to decide *whether* to show it.
 */
export class AuthApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "AuthApiError";
    this.status = status;
  }
}

/** One entry in FastAPI/Pydantic's 422 validation-error `detail` array. */
interface ValidationErrorDetail {
  msg?: string;
}

function isValidationErrorDetail(value: unknown): value is ValidationErrorDetail {
  return typeof value === "object" && value !== null;
}

/**
 * Extract a single human-readable message from a FastAPI error response.
 *
 * FastAPI error bodies come in two shapes this app can receive:
 *   - `HTTPException(detail="...")` -> `{ "detail": "some string" }`
 *     (409 duplicate email, 401 bad credentials)
 *   - Pydantic request validation failures -> `{ "detail": [{ "msg":
 *     "...", "loc": [...], "type": "..." }, ...] }` (422) -- only
 *     reachable if a request bypasses the frontend's zod validation
 *     (src/lib/validation/authSchemas.ts), since that already enforces
 *     the same constraints client-side, but the parser cannot assume
 *     that never happens.
 * Falls back to a generic message if the body doesn't match either
 * shape, or isn't JSON at all (e.g. a 502 from an intermediary proxy).
 */
async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") {
        return detail;
      }
      if (Array.isArray(detail) && detail.length > 0 && isValidationErrorDetail(detail[0])) {
        const first = detail[0];
        if (typeof first.msg === "string") {
          return first.msg;
        }
      }
    }
  } catch {
    // Response body was not JSON -- fall through to the generic message.
  }
  return "Something went wrong. Please try again.";
}

async function postAuthJson<T>(path: string, payload?: unknown): Promise<T> {
  const response = await fetch(`${env.authBaseUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: payload === undefined ? null : JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export interface RegisterInput {
  email: string;
  password: string;
  displayName?: string | undefined;
}

/** POST /auth/register -- a new account, immediately authenticated. */
export function registerUser(input: RegisterInput): Promise<TokenResponse> {
  return postAuthJson<TokenResponse>("/register", {
    email: input.email,
    password: input.password,
    display_name: input.displayName && input.displayName.length > 0 ? input.displayName : null,
  });
}

export interface LoginInput {
  email: string;
  password: string;
}

/** POST /auth/login. */
export function loginUser(input: LoginInput): Promise<TokenResponse> {
  return postAuthJson<TokenResponse>("/login", input);
}

/** POST /auth/logout -- clears the httpOnly cookie; no request body. */
export function logoutUser(): Promise<void> {
  return postAuthJson<void>("/logout");
}
