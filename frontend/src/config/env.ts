// frontend/src/config/env.ts
// Typed, centralised access to build-time environment configuration. The
// rest of the app imports `env` rather than touching `import.meta.env`
// directly, so there is exactly one place that defines defaults and one
// place to change when a new VITE_ variable is added.

export const env = {
  /**
   * Backend API base URL. Falls back to the relative "/api/v1" path, which
   * the Vite dev proxy (vite.config.ts) forwards to http://localhost:8000
   * in development and which a same-origin reverse proxy can serve in
   * production. Set VITE_API_BASE_URL to point at a different origin.
   */
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "/api/v1",
  /**
   * Auth base URL (T-056). Separate from apiBaseUrl on purpose:
   * backend/routers/auth.py mounts at "/auth/*", not under "/api/v1"
   * (see backend/main.py's router registration) -- so this cannot
   * share apiBaseUrl's default. Falls back to the relative "/auth"
   * path, which the Vite dev proxy forwards to http://localhost:8000
   * the same way it already does for "/api". Set VITE_AUTH_BASE_URL to
   * point at a different origin.
   */
  authBaseUrl: import.meta.env.VITE_AUTH_BASE_URL ?? "/auth",
  isDevelopment: import.meta.env.DEV,
  isProduction: import.meta.env.PROD,
} as const;
