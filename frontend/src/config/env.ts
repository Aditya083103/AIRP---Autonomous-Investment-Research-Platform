// frontend/src/config/env.ts
// Typed, centralised access to build-time environment configuration. The
// rest of the app imports `env` rather than touching `import.meta.env`
// directly, so there is exactly one place that defines defaults and one
// place to change when a new VITE_ variable is added.

/**
 * Derive a WebSocket base URL from an absolute VITE_API_BASE_URL, e.g.
 * "https://airp-api.onrender.com/api/v1" becomes "wss://airp-api.onrender.com".
 * Returns undefined when apiBaseUrl is unset or relative (the local-dev
 * default, "/api/v1") -- there is no origin to derive from in that case,
 * and the caller (resolveWebSocketBaseUrl below, used by both
 * useAnalysisStream.ts and useChatStream.ts) falls back to
 * window.location instead, exactly as it did before this derivation
 * existed.
 */
export function deriveWsBaseUrlFromApiBaseUrl(apiBaseUrl: string | undefined): string | undefined {
  if (!apiBaseUrl || !/^https?:\/\//i.test(apiBaseUrl)) {
    return undefined;
  }
  try {
    const parsed = new URL(apiBaseUrl);
    const wsProtocol = parsed.protocol === "https:" ? "wss:" : "ws:";
    return `${wsProtocol}//${parsed.host}`;
  } catch {
    return undefined;
  }
}

/**
 * WebSocket base URL fallback chain (T-074 audit finding C1/F1):
 *   1. explicit VITE_WS_BASE_URL
 *   2. derived from VITE_API_BASE_URL's origin
 *   3. undefined, in which case useAnalysisStream.ts / useChatStream.ts fall back to
 *      window.location, unchanged from their pre-C1 behaviour.
 * This is what makes split-origin deployments (e.g. Vercel frontend +
 * Render backend) work: without it, every WebSocket dialled
 * `wss://<frontend-host>/...` and 404'd, silently killing the live agent
 * progress viewer, the live graph, the debate viewer, and chat streaming.
 */
const wsBaseUrl: string | undefined =
  import.meta.env.VITE_WS_BASE_URL ??
  deriveWsBaseUrlFromApiBaseUrl(import.meta.env.VITE_API_BASE_URL);

/**
 * Resolve the WebSocket base URL a streaming hook should dial, warning
 * loudly in production if neither VITE_WS_BASE_URL nor an absolute
 * VITE_API_BASE_URL is configured.
 *
 * Audit finding (Section C, unit 9): this exact "warn loudly in
 * production when the WS base URL falls back to window.location"
 * behaviour originally shipped only in useChatStream.ts's own private
 * `defaultWebSocketBaseUrl` (B9's fix for the chat widget dialling its
 * own frontend origin and silently failing). useAnalysisStream.ts --
 * the hook powering the live agent-progress viewer, arguably the
 * app's PRIMARY feature -- had an outwardly identical private helper
 * that never received the same fix, so the same misconfiguration
 * (missing VITE_WS_BASE_URL on a split-origin Vercel+Render deploy)
 * silently broke live progress with zero console signal, while chat
 * explained itself. Hoisting the shared logic here, called by both
 * hooks, means there is exactly one place to get this right and no
 * third hook can reintroduce the same gap by copy-pasting a private
 * helper that quietly omits the warning.
 *
 * `isProduction` and `wsBaseUrl` are taken as explicit parameters
 * (rather than this function reading `env` directly) so it can be unit
 * tested without stubbing `import.meta.env` across module re-imports --
 * the same reasoning deriveWsBaseUrlFromApiBaseUrl above is a pure
 * function instead of reading `env` internally.
 */
export function resolveWebSocketBaseUrl(options: {
  wsBaseUrl: string | undefined;
  isProduction: boolean;
  /** Human-readable feature name for the production warning, e.g. "Live analysis progress". */
  callerLabel: string;
}): string {
  const { wsBaseUrl: resolvedWsBaseUrl, isProduction, callerLabel } = options;

  if (resolvedWsBaseUrl) {
    return resolvedWsBaseUrl;
  }

  if (isProduction) {
    console.error(
      `${callerLabel}: no VITE_WS_BASE_URL (or absolute VITE_API_BASE_URL) is ` +
        "configured for this production build -- this socket will dial " +
        "this frontend's own origin, which has no backend listening. Set " +
        "VITE_WS_BASE_URL (or VITE_API_BASE_URL) in the Vercel project's " +
        "environment variables.",
    );
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}`;
}

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
  /**
   * WebSocket base URL, e.g. "wss://airp-api.onrender.com". Undefined when
   * neither VITE_WS_BASE_URL nor an absolute VITE_API_BASE_URL is set --
   * consumers (useAnalysisStream.ts, useChatStream.ts) treat undefined as
   * "derive from window.location", the pre-existing same-origin behaviour.
   * See the fallback chain documented on deriveWsBaseUrlFromApiBaseUrl above.
   */
  wsBaseUrl,
  isDevelopment: import.meta.env.DEV,
  isProduction: import.meta.env.PROD,
} as const;
