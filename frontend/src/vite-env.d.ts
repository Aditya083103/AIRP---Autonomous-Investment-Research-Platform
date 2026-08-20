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
  /**
   * Absolute WebSocket base URL, e.g. "wss://airp-api.onrender.com". Optional
   * on purpose (T-074 audit finding C1/F1): when unset, src/config/env.ts
   * derives one from VITE_API_BASE_URL's origin (http becomes ws, https becomes wss),
   * and when that is also unset (or relative, as the local-dev default is),
   * useAnalysisStream.ts / useChatStream.ts fall back to window.location --
   * which only works when the frontend and backend share an origin. Set
   * this explicitly whenever the frontend and backend are on different
   * hosts (e.g. Vercel + Render), since window.location.host would
   * otherwise point WebSocket connections at the wrong origin entirely.
   */
  readonly VITE_WS_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
