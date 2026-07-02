/// <reference types="vite/client" />

// Augments Vite's built-in ImportMetaEnv with AIRP's own VITE_-prefixed
// variables so `import.meta.env.VITE_API_BASE_URL` is typed, not `any`.
// Only variables read by the app belong here.

interface ImportMetaEnv {
  /**
   * Absolute base URL of the AIRP backend API, e.g.
   * "https://airp-api.onrender.com/api/v1". Optional: in local dev it is
   * left unset and requests fall back to the Vite proxy (see
   * vite.config.ts) via the relative "/api/v1" default in src/config/env.ts.
   */
  readonly VITE_API_BASE_URL?: string;
  /**
   * Absolute base URL of the AIRP auth endpoints (T-056), e.g.
   * "https://airp-api.onrender.com/auth". Separate from
   * VITE_API_BASE_URL because backend/routers/auth.py mounts at "/auth",
   * not under "/api/v1". Optional: in local dev it is left unset and
   * requests fall back to the Vite proxy via the relative "/auth"
   * default in src/config/env.ts.
   */
  readonly VITE_AUTH_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
