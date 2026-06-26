// frontend/src/hooks/useAnalysisStream.ts
//
// AIRP -- Live Agent Progress Stream Hook (T-049)
//
// Connects to WS /api/v1/analysis/{job_id}/stream (backend/routers/websocket.py)
// and exposes the live, in-order sequence of AgentStreamEvent messages the
// backend pushes as each LangGraph node completes.
//
// This hook is the frontend-side proof of T-049's second acceptance
// criterion -- "frontend receives and displays in order" -- ahead of the
// full dashboard UI, which is built in Phase 6 (T-053 onward). It is
// intentionally self-contained (no React Query, no app-wide WebSocket
// context) so it can be dropped into whichever page Phase 6 ends up
// rendering the live progress viewer on without any other Phase 6
// scaffolding needing to exist first.
//
// Usage:
//   const { events, status, connectionStatus, error } = useAnalysisStream({
//     jobId: "11111111-2222-3333-4444-555555555555",
//     token: accessToken,
//   });
//
// Wire format (must match backend.services.ws_broadcaster.AgentStreamEvent
// and backend.models.schemas.AgentStreamEventResponse exactly):
//   { job_id, agent, status, output_preview, progress_percent, is_final }

import { useEffect, useRef, useState } from "react";

/**
 * One message received over WS /api/v1/analysis/{job_id}/stream.
 *
 * Field names and casing are snake_case on purpose -- they are the exact
 * JSON keys backend.services.ws_broadcaster.AgentStreamEvent serialises,
 * not a TypeScript-idiomatic re-shaping. Keeping the wire shape and the
 * TypeScript type identical means a payload can be trusted as-is (after
 * the runtime guard in isAgentStreamEvent below) without a separate
 * camelCase mapping step that could silently drift from the backend
 * schema over time.
 */
export interface AgentStreamEvent {
  job_id: string;
  agent: string;
  status: string;
  output_preview: string;
  progress_percent: number;
  is_final: boolean;
}

/** Connection lifecycle as observed from the browser side. */
export type AnalysisStreamConnectionStatus = "idle" | "connecting" | "open" | "closed" | "error";

export interface UseAnalysisStreamOptions {
  /** UUID of the analysis job to stream -- the {job_id} path segment. */
  jobId: string;
  /**
   * Bearer access token from POST /auth/login. Sent as a `token` query
   * parameter because browsers cannot set custom headers on a WebSocket
   * handshake -- see backend/routers/websocket.py's own "Why query-param
   * auth" docstring section for the full rationale.
   */
  token: string;
  /**
   * Base WebSocket URL, e.g. "ws://localhost:8000" in dev or
   * "wss://api.example.com" in production. Defaults to deriving one from
   * `window.location` so the hook works out of the box when the frontend
   * and backend share an origin (e.g. behind the same reverse proxy).
   */
  baseUrl?: string;
  /** Set to false to skip connecting (e.g. before jobId is known). */
  enabled?: boolean;
}

export interface UseAnalysisStreamResult {
  /** Every AgentStreamEvent received so far, in arrival order. */
  events: AgentStreamEvent[];
  /** The most recent event's `status` field, or null before the first event. */
  status: string | null;
  /** The most recent event's `progress_percent`, or 0 before the first event. */
  progressPercent: number;
  /** True once the server has sent the event with `is_final: true`. */
  isComplete: boolean;
  /** Current browser-side WebSocket lifecycle state. */
  connectionStatus: AnalysisStreamConnectionStatus;
  /** Human-readable error message, if the connection failed or was rejected. */
  error: string | null;
}

function defaultWebSocketBaseUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}`;
}

/**
 * Narrow an unknown decoded-JSON value to AgentStreamEvent at runtime.
 *
 * A WebSocket message is just bytes on the wire -- TypeScript's static
 * typing gives no guarantee the backend actually sent the shape this
 * hook expects (a backend bug, a proxy mangling the payload, or a future
 * schema change could all produce something else). Without this guard,
 * a malformed message would either crash the render that reads
 * `event.progress_percent` or silently display `undefined` -- this
 * function turns either failure mode into a single, loggable rejection
 * point instead.
 */
function isAgentStreamEvent(value: unknown): value is AgentStreamEvent {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.job_id === "string" &&
    typeof candidate.agent === "string" &&
    typeof candidate.status === "string" &&
    typeof candidate.output_preview === "string" &&
    typeof candidate.progress_percent === "number" &&
    typeof candidate.is_final === "boolean"
  );
}

/**
 * Subscribe to live agent-completion events for one analysis job.
 *
 * Opens exactly one WebSocket connection for the lifetime of
 * `{ jobId, token, enabled }` staying the same, and closes it on
 * unmount or whenever any of those inputs change -- React's effect
 * cleanup contract, applied to a WebSocket the same way it would be
 * applied to any other subscription.
 */
export function useAnalysisStream(options: UseAnalysisStreamOptions): UseAnalysisStreamResult {
  const { jobId, token, baseUrl, enabled = true } = options;

  const [events, setEvents] = useState<AgentStreamEvent[]>([]);
  const [connectionStatus, setConnectionStatus] = useState<AnalysisStreamConnectionStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  // Guards against state updates from a socket that belonged to a PRIOR
  // render's effect (e.g. jobId changed mid-flight) -- without this, a
  // slow-to-arrive message from the old socket could land after the new
  // one has already started receiving events, corrupting ordering.
  const isCurrentEffectRef = useRef(true);

  useEffect(() => {
    isCurrentEffectRef.current = true;

    if (!enabled || jobId === "" || token === "") {
      return undefined;
    }

    setEvents([]);
    setError(null);
    setConnectionStatus("connecting");

    const resolvedBaseUrl = baseUrl ?? defaultWebSocketBaseUrl();
    const url = `${resolvedBaseUrl}/api/v1/analysis/${jobId}/stream?token=${encodeURIComponent(
      token,
    )}`;

    const socket = new WebSocket(url);

    socket.onopen = (): void => {
      if (!isCurrentEffectRef.current) return;
      setConnectionStatus("open");
    };

    socket.onmessage = (messageEvent: MessageEvent<string>): void => {
      if (!isCurrentEffectRef.current) return;

      let parsed: unknown;
      try {
        parsed = JSON.parse(messageEvent.data);
      } catch {
        setError("Received a malformed (non-JSON) message from the server.");
        return;
      }

      if (!isAgentStreamEvent(parsed)) {
        setError("Received a message that does not match AgentStreamEvent.");
        return;
      }

      // Append, never replace -- preserves arrival order for every
      // consumer of `events`, which is the literal acceptance criterion
      // ("frontend receives and displays in order").
      setEvents((previous) => [...previous, parsed]);
    };

    socket.onerror = (): void => {
      if (!isCurrentEffectRef.current) return;
      setConnectionStatus("error");
      setError("WebSocket connection error.");
    };

    socket.onclose = (closeEvent: CloseEvent): void => {
      if (!isCurrentEffectRef.current) return;
      setConnectionStatus("closed");
      // 1000 = normal closure (backend.routers.websocket's happy path);
      // 4401/4404 are the two application-specific codes that module
      // documents for auth failure and job-not-found/not-yours.
      if (closeEvent.code === 4401) {
        setError("Not authorized to view this analysis (invalid or expired token).");
      } else if (closeEvent.code === 4404) {
        setError("Analysis job not found, or it does not belong to you.");
      } else if (closeEvent.code !== 1000) {
        setError(`Connection closed unexpectedly (code ${closeEvent.code}).`);
      }
    };

    return (): void => {
      isCurrentEffectRef.current = false;
      socket.close();
    };
    // baseUrl is intentionally excluded from the dependency array below:
    // it is expected to be a stable caller-side constant (or derive
    // identically every render via defaultWebSocketBaseUrl), and
    // including it would reconnect on every render for callers who pass
    // a freshly-computed string literal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, token, enabled]);

  const lastEvent = events.length > 0 ? events[events.length - 1] : undefined;

  return {
    events,
    status: lastEvent?.status ?? null,
    progressPercent: lastEvent?.progress_percent ?? 0,
    isComplete: lastEvent?.is_final ?? false,
    connectionStatus,
    error,
  };
}
