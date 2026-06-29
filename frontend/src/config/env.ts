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
  isDevelopment: import.meta.env.DEV,
  isProduction: import.meta.env.PROD,
} as const;
