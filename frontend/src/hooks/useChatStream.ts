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

import { ChatApiError, deleteChatMessagesFrom } from "@/api/chat";
import { env, resolveWebSocketBaseUrl } from "@/config/env";

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

// Reconnection (Section C, unit 9 audit finding -- this hook was flagged as
// deferred when useAnalysisStream.ts got its own reconnect logic, pending a
// dedicated design pass for chat's more complex, stateful, multi-turn
// connection). Same bounded/backed-off shape as useAnalysisStream.ts
// (1s/2s/3s, 3 attempts) for the identical reasoning -- a transient network
// blip or the documented Vite-dev-proxy quirk should not permanently strand
// the widget, but a genuinely dead backend must still surface as an error
// rather than retry forever.
//
// The one substantive difference from useAnalysisStream: THAT hook resets
// `events` to `[]` on every connection attempt because the backend replays
// a job's full event history on every fresh connect. chat_stream.py has no
// such replay -- it is a persistent, stateful, multi-turn connection, and a
// resumed session's history is already seeded once via `initialMessages`
// (GET .../messages) when the session is first opened. Resetting `messages`
// on a RECONNECT of the same session would silently wipe the transcript the
// user is looking at. So `messages` is only reset to `initialMessagesRef`
// when `sessionId`/`token` genuinely change to a new identity (see
// lastIdentityRef below) -- never on a reconnect-triggered re-run of the
// SAME session.
const MAX_RECONNECT_ATTEMPTS = 3;
const RECONNECT_BASE_DELAY_MS = 1000;

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
  /**
   * (B9) The server's real chat_messages.id for this message, or null
   * until it is known. A message loaded from GET .../messages (a
   * resumed session) always has this set from the start. A message
   * sent live over this connection starts null and is filled in once
   * the backend confirms it: a user message's id arrives on the
   * SAME turn's 'start' event (see chat_stream.py's "Why 'start' now
   * carries the user message's id"), an assistant message's on its
   * own 'done'. Required to call editMessage -- see that function's
   * own docstring below.
   */
  serverId: string | null;
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
  /**
   * (B9) A previously-persisted transcript to seed `messages` with when
   * this sessionId's connection is (re)established, instead of the
   * usual empty transcript -- how useChatWidget.ts resumes a past
   * session picked from the conversation list (GET .../messages,
   * converted to ChatWidgetMessage[]) so re-opening an old
   * conversation shows its history immediately rather than looking
   * like a blank new chat. Ignored (transcript starts empty, as
   * before) when omitted or when sessionId changes to a session this
   * was not provided for -- callers are responsible for keeping this
   * in sync with `sessionId` (see useChatWidget's openHistorySession).
   */
  initialMessages?: ChatWidgetMessage[];
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
  /**
   * (B9) Edit a past user message: deletes it and everything the
   * assistant said after it (DELETE .../messages/{id}, matching the
   * Claude UX), then re-sends `newContent` as a fresh turn over this
   * SAME connection -- reusing `sendMessage`'s own turn mechanics
   * rather than a separate regeneration path. `localMessageId` is a
   * ChatWidgetMessage.id from `messages` (its role must be 'user' and
   * its `serverId` must be non-null -- a message whose id is not yet
   * confirmed, or an assistant message, cannot be edited; both are a
   * silent no-op returning false rather than throwing, since this is
   * always called from a UI affordance that itself decides whether to
   * offer editing at all). Returns whether the edit actually went
   * through; a failure (network, 404, 422) is also surfaced via
   * `editError`.
   */
  editMessage: (localMessageId: string, newContent: string) => Promise<boolean>;
  /** True while an editMessage() call's DELETE request is in flight. */
  isEditingMessage: boolean;
  /** Set when the most recent editMessage() call failed. Cleared at the start of the next attempt. */
  editError: string | null;
}

const LOCAL_ID_PREFIX = "local-";

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
  const { sessionId, token, baseUrl, enabled = true, initialMessages } = options;

  const [messages, setMessages] = useState<ChatWidgetMessage[]>([]);
  const [connectionStatus, setConnectionStatus] = useState<ChatStreamConnectionStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  // (B9) Always holds the LATEST `initialMessages` prop, read by the
  // connect effect below at the moment it (re)runs -- NOT added to
  // that effect's own dependency array, since `initialMessages` is
  // typically a freshly-computed array on every render (see
  // useChatWidget's historyMessages) and must not itself trigger a
  // reconnect. Declared (and kept updated) before the connect effect
  // below so React's in-declaration-order effect execution guarantees
  // this ref is current by the time that effect reads it, even when
  // both `sessionId` and `initialMessages` change in the same commit
  // (opening a session picked from the conversation list).
  const initialMessagesRef = useRef<ChatWidgetMessage[]>(initialMessages ?? []);
  useEffect(() => {
    initialMessagesRef.current = initialMessages ?? [];
  }, [initialMessages]);

  // Guards against state updates from a socket that belonged to a PRIOR
  // effect run (a scope switch discarding the old session -- see
  // useChatWidget.ts's "why a session is discarded" note -- or React
  // 18 StrictMode's dev-only mount->cleanup->mount double-invoke).
  // Doubles as socketRef: the current effect's own socket instance,
  // read by sendMessage below.
  //
  // BUGFIX (B9, root cause of "Starting a new conversation..." then
  // "Connection closed unexpectedly (code 1005)"): this used to be a
  // single shared `useRef(true)` boolean (`isCurrentEffectRef`), set
  // true at the top of every effect run and false in that same run's
  // cleanup -- the exact pattern useAnalysisStream.ts's own
  // currentSocketRef BUGFIX comment already documents as broken and
  // replaced, for the identical reason, but that fix was never ported
  // to this sibling hook when it was built. Concretely: switching chat
  // scope (navigating from one memo to another, or memo <-> portfolio)
  // makes useChatWidget discard the old session, so this hook's effect
  // tears down socket A (still finishing its close handshake, over a
  // real network -- no StrictMode needed to trigger this) while a NEW
  // effect run opens socket B for the freshly-created session and
  // resets the SAME shared flag back to true. Socket A's onclose then
  // fires asynchronously, sees the flag reading true again (set by B's
  // run, not A's), and incorrectly overwrites the brand-new session's
  // state with a phantom "Connection closed unexpectedly" error --
  // exactly the screenshot symptom, both messages rendered together. A
  // ref holding the CURRENT effect run's own socket instance (compared
  // by reference, not a shared boolean) makes every handler's
  // staleness check specific to the exact socket it was attached to,
  // immune to a later effect resetting a shared flag out from under an
  // earlier one's in-flight callbacks.
  const currentSocketRef = useRef<WebSocket | null>(null);
  // Client-local id for the assistant message currently streaming, if
  // any -- set on 'start', cleared on 'done'/'error'. A ref (not
  // state) because onmessage handlers need the LIVE value, not one
  // captured in a stale closure from when the effect first ran.
  const streamingMessageIdRef = useRef<string | null>(null);
  // (B9) Client-local id of the user message THIS turn just sent,
  // still awaiting the backend's confirmed real id -- set in
  // sendMessage, consumed (and cleared) the moment the matching
  // 'start' event arrives with that id. See ChatWidgetMessage.serverId
  // and editMessage's own docstrings for why this hand-off exists.
  const pendingUserLocalIdRef = useRef<string | null>(null);
  const nextLocalIdRef = useRef(0);

  // Reconnection bookkeeping -- see the MAX_RECONNECT_ATTEMPTS/
  // RECONNECT_BASE_DELAY_MS module comment above for the full rationale.
  // `reconnectNonce` is bumped (by the scheduled setTimeout in onclose
  // below) to make THIS SAME effect re-run and reopen a socket, exactly
  // mirroring useAnalysisStream.ts's identical mechanism so this
  // reconnect attempt inherits every one of the effect's existing
  // staleness/cleanup guarantees (currentSocketRef above) for free,
  // rather than a second, parallel connection routine. `lastIdentityRef`
  // distinguishes "this run is a genuine new session" (sessionId/token
  // actually changed -- reset the attempt counter AND the transcript)
  // from "this run is a scheduled reconnect for the SAME session" (leave
  // both alone).
  const [reconnectNonce, setReconnectNonce] = useState(0);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastIdentityRef = useRef<string | null>(null);

  const allocateLocalId = useCallback((): string => {
    nextLocalIdRef.current += 1;
    return `${LOCAL_ID_PREFIX}${nextLocalIdRef.current}`;
  }, []);

  useEffect(() => {
    const identity = `${sessionId}:${token}`;
    const isNewIdentity = lastIdentityRef.current !== identity;
    if (isNewIdentity) {
      lastIdentityRef.current = identity;
      reconnectAttemptRef.current = 0;
    }

    streamingMessageIdRef.current = null;
    pendingUserLocalIdRef.current = null;

    if (!enabled || sessionId === null || sessionId === "" || token === null || token === "") {
      currentSocketRef.current = null;
      return undefined;
    }

    // Only reset the transcript on a genuine new session -- never on a
    // reconnect-triggered re-run of the SAME session, which would
    // otherwise silently wipe out everything sent/received since the
    // widget opened. See the MAX_RECONNECT_ATTEMPTS module comment above.
    if (isNewIdentity) {
      setMessages(initialMessagesRef.current);
    }
    setError(null);
    setConnectionStatus("connecting");

    const resolvedBaseUrl =
      baseUrl ??
      resolveWebSocketBaseUrl({
        wsBaseUrl: env.wsBaseUrl,
        isProduction: env.isProduction,
        callerLabel: "AIRP Assistant",
      });
    const url = `${resolvedBaseUrl}/api/v1/chat/${sessionId}/stream?token=${encodeURIComponent(
      token,
    )}`;

    const socket = new WebSocket(url);
    currentSocketRef.current = socket;

    socket.onopen = (): void => {
      if (currentSocketRef.current !== socket) return;
      // A successful connection -- whether the very first one or a
      // reconnect -- clears the backoff counter, so a LATER disconnect
      // gets its own full set of MAX_RECONNECT_ATTEMPTS rather than
      // inheriting a partially-used budget from an unrelated earlier
      // blip. Mirrors useAnalysisStream.ts's identical reasoning.
      reconnectAttemptRef.current = 0;
      setConnectionStatus("open");
    };

    socket.onmessage = (messageEvent: MessageEvent<string>): void => {
      if (currentSocketRef.current !== socket) return;

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
          // (B9) 'start' also carries the id the backend just
          // assigned to the user message THIS turn sent -- fill it
          // into that message's serverId (see ChatWidgetMessage's own
          // docstring) so it becomes editable.
          const confirmedUserLocalId = pendingUserLocalIdRef.current;
          const confirmedUserServerId = parsed.message_id;
          pendingUserLocalIdRef.current = null;
          setMessages((previous) => {
            const withAssistantPlaceholder: ChatWidgetMessage[] = [
              ...previous,
              {
                id: localId,
                role: "assistant",
                content: "",
                isStreaming: true,
                isError: false,
                serverId: null,
              },
            ];
            if (confirmedUserLocalId === null || confirmedUserServerId === null) {
              return withAssistantPlaceholder;
            }
            return withAssistantPlaceholder.map((message) =>
              message.id === confirmedUserLocalId
                ? { ...message, serverId: confirmedUserServerId }
                : message,
            );
          });
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
          const finishedServerId = parsed.message_id;
          streamingMessageIdRef.current = null;
          if (streamingId === null) break;
          setMessages((previous) =>
            previous.map((message) =>
              message.id === streamingId
                ? { ...message, isStreaming: false, serverId: finishedServerId }
                : message,
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
                serverId: null,
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
      if (currentSocketRef.current !== socket) return;
      setConnectionStatus("error");
      setError("WebSocket connection error.");
    };

    socket.onclose = (closeEvent: CloseEvent): void => {
      if (currentSocketRef.current !== socket) return;
      setConnectionStatus("closed");

      // A turn that was actively streaming will never receive its
      // 'done' now -- mark it interrupted rather than leaving it stuck
      // "isStreaming: true" forever once the widget reconnects (or, if
      // reconnect attempts are exhausted, forever period). Mirrors the
      // wording/shape of the existing per-turn 'error' event handling
      // above for consistency.
      const interruptedStreamingId = streamingMessageIdRef.current;
      streamingMessageIdRef.current = null;
      pendingUserLocalIdRef.current = null;
      if (interruptedStreamingId !== null) {
        setMessages((previous) =>
          previous.map((message) =>
            message.id === interruptedStreamingId
              ? {
                  ...message,
                  isStreaming: false,
                  isError: true,
                  content: "Connection lost before this reply finished.",
                }
              : message,
          ),
        );
      }

      if (closeEvent.code === 4401) {
        setError("Not authorized to use this chat session (invalid or expired token).");
      } else if (closeEvent.code === 4404) {
        setError("Chat session not found, or it does not belong to you.");
      } else if (closeEvent.code !== 1000) {
        // The connection ended unexpectedly -- attempt a bounded,
        // backed-off reconnect (see MAX_RECONNECT_ATTEMPTS/
        // RECONNECT_BASE_DELAY_MS above) rather than stranding the
        // widget on a dead connection. Unlike useAnalysisStream, there
        // is no "already received the terminal event, so any close now
        // is just normal teardown" case here -- a chat connection has
        // no terminal event; it is expected to stay open indefinitely
        // between turns, so ANY non-1000 close while the widget is still
        // mounted is worth attempting to recover from.
        if (reconnectAttemptRef.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptRef.current += 1;
          const attempt = reconnectAttemptRef.current;
          setError(
            `Connection lost -- reconnecting (attempt ${attempt}/${MAX_RECONNECT_ATTEMPTS})…`,
          );
          reconnectTimeoutRef.current = setTimeout(() => {
            setReconnectNonce((previous) => previous + 1);
          }, RECONNECT_BASE_DELAY_MS * attempt);
        } else {
          setError(
            `Connection closed unexpectedly (code ${closeEvent.code}) after ` +
              `${MAX_RECONNECT_ATTEMPTS} reconnect attempts.`,
          );
        }
      }
    };

    return (): void => {
      if (reconnectTimeoutRef.current !== null) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      if (currentSocketRef.current === socket) {
        currentSocketRef.current = null;
      }
      socket.close();
    };
    // baseUrl is intentionally excluded -- same rationale as
    // useAnalysisStream's identical exclusion.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, token, enabled, reconnectNonce]);

  const sendMessage = useCallback(
    (text: string): void => {
      const trimmed = text.trim();
      if (trimmed.length === 0) {
        return;
      }
      const socket = currentSocketRef.current;
      if (socket === null || socket.readyState !== WebSocket.OPEN) {
        return;
      }

      const localId = allocateLocalId();
      // (B9) Recorded so the 'start' event this turn provokes can fill
      // in this message's real serverId -- see that case's own comment.
      pendingUserLocalIdRef.current = localId;
      setMessages((previous) => [
        ...previous,
        {
          id: localId,
          role: "user",
          content: trimmed,
          isStreaming: false,
          isError: false,
          serverId: null,
        },
      ]);
      socket.send(JSON.stringify({ message: trimmed }));
    },
    [allocateLocalId],
  );

  const [isEditingMessage, setIsEditingMessage] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  const isAssistantTyping = messages.some(
    (message) => message.role === "assistant" && message.isStreaming,
  );

  const editMessage = useCallback(
    async (localMessageId: string, newContent: string): Promise<boolean> => {
      const trimmed = newContent.trim();
      if (trimmed.length === 0) {
        return false;
      }
      if (isAssistantTyping) {
        setEditError("Please wait for the current reply to finish before editing.");
        return false;
      }
      const target = messages.find((message) => message.id === localMessageId);
      if (target === undefined || target.role !== "user") {
        return false;
      }
      if (target.serverId === null) {
        setEditError("This message is not ready to edit yet -- try again in a moment.");
        return false;
      }
      if (sessionId === null || token === null) {
        return false;
      }

      setIsEditingMessage(true);
      setEditError(null);
      try {
        await deleteChatMessagesFrom({
          accessToken: token,
          sessionId,
          messageId: target.serverId,
        });
      } catch (caught) {
        setEditError(
          caught instanceof ChatApiError
            ? caught.message
            : "Could not edit that message. Please try again.",
        );
        return false;
      } finally {
        setIsEditingMessage(false);
      }

      // Drop the edited message and everything after it, then re-send
      // the edited text as a fresh turn -- two functional updates
      // queued in this order within the same commit, so the fresh
      // turn's user bubble is appended AFTER the truncation, never
      // before it (see this function's own docstring on
      // UseChatStreamResult).
      setMessages((previous) => {
        const index = previous.findIndex((message) => message.id === localMessageId);
        return index === -1 ? previous : previous.slice(0, index);
      });
      sendMessage(trimmed);
      return true;
    },
    [messages, isAssistantTyping, sessionId, token, sendMessage],
  );

  return {
    messages,
    connectionStatus,
    isAssistantTyping,
    error,
    sendMessage,
    editMessage,
    isEditingMessage,
    editError,
  };
}
