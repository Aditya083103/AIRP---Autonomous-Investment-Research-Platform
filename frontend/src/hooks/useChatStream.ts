// frontend/src/hooks/useChatStream.ts
// AIRP -- AIRP Assistant chat stream hook (T-105)
//
// Connects to WS /api/v1/chat/{session_id}/stream (backend/routers/
// chat_stream.py, T-104) for one chat session and exposes the running
// transcript plus a `sendMessage` function. Structurally this is
// src/hooks/useAnalysisStream.ts's (T-049) sibling -- same "open one
// socket for the lifetime of the identifying props, close on unmount
// or when they change" effect shape, same runtime-guard-before-trust
// discipline for anything read off the wire -- adapted to chat's very
// different wire protocol:
//
//   * useAnalysisStream is receive-only (the client never sends
//     anything over that socket); this hook also SENDS
//     `{ "message": "<text>" }` per turn (T-104's own documented
//     client protocol).
//   * useAnalysisStream's server closes the connection once after
//     exactly one `is_final: true` event (one analysis run, one
//     socket). T-104's server instead keeps ONE connection open across
//     MANY turns -- "receive loop: for each incoming message, stream
//     one full reply back, then wait for the next message on the SAME
//     connection" (chat_stream.py's own module docstring) -- so this
//     hook opens its socket once per sessionId and lets sendMessage
//     reuse it turn after turn, rather than reconnecting per message.
//   * Five event_type values instead of one implicit "every message is
//     a progress update" shape: 'start' begins a new streaming
//     assistant message, 'token' appends to it, 'heartbeat' is a
//     content-free keepalive (ignored here beyond proving the
//     connection is alive), 'done' finalises it, 'error' surfaces a
//     failed turn WITHOUT closing the connection (T-104's own "a bad
//     turn does not close the connection" guarantee) -- see
//     ChatStreamEvent below.

import { useCallback, useEffect, useRef, useState } from "react";

import { env } from "@/config/env";

/** One push payload received over WS /api/v1/chat/{session_id}/stream. See backend/routers/chat_stream.py's ChatStreamEvent for the authoritative field meanings. */
export interface ChatStreamEvent {
  session_id: string;
  event_type: string;
  token: string;
  message_id: string | null;
  is_final: boolean;
  error: string | null;
}

/** Connection lifecycle as observed from the browser side. */
export type ChatStreamConnectionStatus = "idle" | "connecting" | "open" | "closed" | "error";

/** One message rendered in the widget's transcript -- both user turns (sent locally) and assistant turns (built up token by token). */
export interface ChatWidgetMessage {
  /** Client-local id (never the server's UUID -- see LOCAL_ID_PREFIX below). Stable across re-renders, used as the React list key. */
  id: string;
  role: "user" | "assistant";
  content: string;
  /** True while an assistant message's tokens are still arriving (between 'start' and 'done'/'error'). Always false for user messages. */
  isStreaming: boolean;
  /** True when this assistant message ended in a turn-level error (backend event_type='error'). */
  isError: boolean;
}

export interface UseChatStreamOptions {
  /** UUID of the chat session to stream -- the {session_id} path segment. Pass null before a session has been created yet. */
  sessionId: string | null;
  /** Bearer access token from useAuth(). Sent as a `token` query parameter -- same reasoning as useAnalysisStream's own `token` option. */
  token: string | null;
  /** Base WebSocket URL. Defaults to deriving one from `window.location`, same as useAnalysisStream. */
  baseUrl?: string;
  /** Set to false to skip connecting (e.g. before the widget panel has been opened, or before a session exists). */
  enabled?: boolean;
}

export interface UseChatStreamResult {
  /** The running transcript, oldest first: every user turn plus every assistant reply (in progress or finished). */
  messages: ChatWidgetMessage[];
  connectionStatus: ChatStreamConnectionStatus;
  /** True while an assistant reply is currently streaming -- callers use this to disable the composer until the turn finishes. */
  isAssistantTyping: boolean;
  /** Human-readable connection-level error (auth/not-found/socket failure) -- distinct from a per-turn error, which is rendered inline on the affected message instead. */
  error: string | null;
  /** Send one user message over the open connection. No-op (does nothing) when the connection is not open. */
  sendMessage: (text: string) => void;
}

const LOCAL_ID_PREFIX = "local-";

function defaultWebSocketBaseUrl(): string {
  // T-074 audit finding C1/F1: see useAnalysisStream.ts's identical helper
  // for the full rationale -- prefer env.wsBaseUrl so split-origin
  // deployments dial the right host, falling back to window.location only
  // when neither VITE_WS_BASE_URL nor an absolute VITE_API_BASE_URL is set.
  if (env.wsBaseUrl) {
    return env.wsBaseUrl;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}`;
}

/**
 * Narrow an unknown decoded-JSON value to ChatStreamEvent at runtime --
 * see useAnalysisStream's isAgentStreamEvent for why this guard exists
 * at all (a WebSocket message is just bytes; nothing about TypeScript's
 * static typing guarantees the backend actually sent this shape).
 */
function isChatStreamEvent(value: unknown): value is ChatStreamEvent {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.session_id === "string" &&
    typeof candidate.event_type === "string" &&
    typeof candidate.token === "string" &&
    (candidate.message_id === null || typeof candidate.message_id === "string") &&
    typeof candidate.is_final === "boolean" &&
    (candidate.error === null || typeof candidate.error === "string")
  );
}

/**
 * Subscribe to one chat session's live token stream and drive its turn
 * loop.
 *
 * Opens exactly one WebSocket connection for the lifetime of
 * `{ sessionId, token, enabled }` staying the same, and closes it on
 * unmount or whenever any of those inputs change -- identical contract
 * to useAnalysisStream's own effect.
 */
export function useChatStream(options: UseChatStreamOptions): UseChatStreamResult {
  const { sessionId, token, baseUrl, enabled = true } = options;

  const [messages, setMessages] = useState<ChatWidgetMessage[]>([]);
  const [connectionStatus, setConnectionStatus] = useState<ChatStreamConnectionStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  // Guards against state updates from a socket belonging to a PRIOR
  // render's effect -- same purpose as useAnalysisStream's own
  // isCurrentEffectRef.
  const isCurrentEffectRef = useRef(true);
  // Client-local id for the assistant message currently streaming, if
  // any -- set on 'start', cleared on 'done'/'error'. A ref (not
  // state) because onmessage handlers need the LIVE value, not one
  // captured in a stale closure from when the effect first ran.
  const streamingMessageIdRef = useRef<string | null>(null);
  const nextLocalIdRef = useRef(0);

  const allocateLocalId = useCallback((): string => {
    nextLocalIdRef.current += 1;
    return `${LOCAL_ID_PREFIX}${nextLocalIdRef.current}`;
  }, []);

  useEffect(() => {
    isCurrentEffectRef.current = true;
    streamingMessageIdRef.current = null;

    if (!enabled || sessionId === null || sessionId === "" || token === null || token === "") {
      return undefined;
    }

    setMessages([]);
    setError(null);
    setConnectionStatus("connecting");

    const resolvedBaseUrl = baseUrl ?? defaultWebSocketBaseUrl();
    const url = `${resolvedBaseUrl}/api/v1/chat/${sessionId}/stream?token=${encodeURIComponent(
      token,
    )}`;

    const socket = new WebSocket(url);
    socketRef.current = socket;

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

      if (!isChatStreamEvent(parsed)) {
        setError("Received a message that does not match ChatStreamEvent.");
        return;
      }

      switch (parsed.event_type) {
        case "start": {
          const localId = allocateLocalId();
          streamingMessageIdRef.current = localId;
          setMessages((previous) => [
            ...previous,
            { id: localId, role: "assistant", content: "", isStreaming: true, isError: false },
          ]);
          break;
        }
        case "token": {
          const streamingId = streamingMessageIdRef.current;
          if (streamingId === null) {
            // A token arrived with no matching 'start' -- defensive
            // guard only; the server always sends 'start' first. Drop
            // it rather than crashing the render.
            break;
          }
          setMessages((previous) =>
            previous.map((message) =>
              message.id === streamingId
                ? { ...message, content: message.content + parsed.token }
                : message,
            ),
          );
          break;
        }
        case "heartbeat":
          // Content-free keepalive -- nothing to render.
          break;
        case "done": {
          const streamingId = streamingMessageIdRef.current;
          streamingMessageIdRef.current = null;
          if (streamingId === null) break;
          setMessages((previous) =>
            previous.map((message) =>
              message.id === streamingId ? { ...message, isStreaming: false } : message,
            ),
          );
          break;
        }
        case "error": {
          const streamingId = streamingMessageIdRef.current;
          streamingMessageIdRef.current = null;
          const errorText = parsed.error ?? "The AIRP Assistant could not complete that reply.";
          if (streamingId !== null) {
            // A turn that had already started streaming failed
            // mid-flight -- mark the in-progress message as errored
            // rather than leaving it stuck "streaming" forever.
            setMessages((previous) =>
              previous.map((message) =>
                message.id === streamingId
                  ? { ...message, isStreaming: false, isError: true, content: errorText }
                  : message,
              ),
            );
          } else {
            // A turn-level error with no in-progress message (e.g. the
            // client sent a malformed payload) -- surface it as its
            // own inline assistant bubble.
            setMessages((previous) => [
              ...previous,
              {
                id: allocateLocalId(),
                role: "assistant",
                content: errorText,
                isStreaming: false,
                isError: true,
              },
            ]);
          }
          break;
        }
        default:
          // Unknown event_type -- ignore rather than throw, the same
          // forward-compatibility stance useAnalysisStream takes on an
          // unrecognised (but well-formed) message.
          break;
      }
    };

    socket.onerror = (): void => {
      if (!isCurrentEffectRef.current) return;
      setConnectionStatus("error");
      setError("WebSocket connection error.");
    };

    socket.onclose = (closeEvent: CloseEvent): void => {
      if (!isCurrentEffectRef.current) return;
      setConnectionStatus("closed");
      if (closeEvent.code === 4401) {
        setError("Not authorized to use this chat session (invalid or expired token).");
      } else if (closeEvent.code === 4404) {
        setError("Chat session not found, or it does not belong to you.");
      } else if (closeEvent.code !== 1000) {
        setError(`Connection closed unexpectedly (code ${closeEvent.code}).`);
      }
    };

    return (): void => {
      isCurrentEffectRef.current = false;
      socketRef.current = null;
      socket.close();
    };
    // baseUrl is intentionally excluded -- same rationale as
    // useAnalysisStream's identical exclusion.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, token, enabled]);

  const sendMessage = useCallback(
    (text: string): void => {
      const trimmed = text.trim();
      if (trimmed.length === 0) {
        return;
      }
      const socket = socketRef.current;
      if (socket === null || socket.readyState !== WebSocket.OPEN) {
        return;
      }

      setMessages((previous) => [
        ...previous,
        {
          id: allocateLocalId(),
          role: "user",
          content: trimmed,
          isStreaming: false,
          isError: false,
        },
      ]);
      socket.send(JSON.stringify({ message: trimmed }));
    },
    [allocateLocalId],
  );

  const isAssistantTyping = messages.some(
    (message) => message.role === "assistant" && message.isStreaming,
  );

  return {
    messages,
    connectionStatus,
    isAssistantTyping,
    error,
    sendMessage,
  };
}
