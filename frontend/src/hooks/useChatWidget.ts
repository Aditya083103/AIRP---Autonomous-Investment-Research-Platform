// frontend/src/hooks/useChatWidget.ts
// AIRP -- ChatWidget controller hook (T-105)
//
// Composes the three pieces ChatWidget.tsx needs and that don't belong
// mixed into a render function: which scope (memo_scoped vs
// portfolio_wide) the current route implies (src/lib/chat/chatScope.ts),
// lazily creating a ChatSession for that scope the first time the panel
// is opened (POST /api/v1/chat/sessions, T-103), and the live
// token stream once a session exists (useChatStream, T-104). Pulling
// this into its own hook -- rather than inlining all three directly in
// ChatWidget.tsx -- keeps that component to rendering/markup concerns
// only and makes the open/create/reset state machine unit-testable via
// renderHook without mounting any DOM.
//
// Why the session is created lazily on open, not eagerly on mount
// ------------------------------------------------------------------------
// ChatWidget is always mounted (RootLayout renders it on every
// authenticated route) but the person may never open it in a given
// visit. Creating a ChatSession row (T-099's schema) for every page
// load, whether or not the person ever asks a question, would litter
// chat_sessions with empty sessions -- POST /api/v1/chat/sessions only
// fires the first time isOpen becomes true for a given scope.
//
// Why a session is discarded (not reused) when the scope changes
// ------------------------------------------------------------------------
// T-099's schema ties session_type + analysis_id to one ChatSession row
// permanently at creation time (enforced server-side by the
// ck_chat_sessions_scope_consistency CHECK constraint
// backend/models/schemas.py's own ChatSessionCreateRequest docstring
// references). Navigating from one memo to a different one, or between
// memo and portfolio mode, is a genuinely different scope and must get
// its own session -- reusing the old session's id against a new scope
// is not an option the backend even allows, so this hook clears its
// local session state the moment the scope's identity
// (chatScopeKey) changes, and the next open (or, if the panel is
// already open, the very next render) creates a fresh one.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

import {
  ChatApiError,
  createChatSession,
  getChatSessionMessages,
  listChatSessions,
} from "@/api/chat";
import { useAuth } from "@/hooks/useAuth";
import {
  useChatStream,
  type ChatStreamConnectionStatus,
  type ChatWidgetMessage,
} from "@/hooks/useChatStream";
import { chatScopeKey, deriveChatScope, type ChatScope } from "@/lib/chat/chatScope";
import { type ChatSessionResponse } from "@/types/chat";

// (B9) Requested when resuming a past session's transcript -- matches
// backend/routers/chat_stream.py's own MAX_MESSAGES_PAGE_SIZE, the
// same full-history page size that router replays into every LLM
// call, so resuming a session shows exactly the context the AIRP
// Assistant itself is answering follow-ups against.
const HISTORY_MESSAGES_LIMIT = 200;

/** Converts a persisted ChatMessageResponse page into the widget's transcript shape. Rows with role 'system'/'tool' are skipped -- never rendered as a chat bubble, matching backend.services.chat_llm.build_chat_messages's identical skip of non user/assistant rows. */
function toWidgetMessages(
  items: readonly { id: string; role: string; content: string }[],
): ChatWidgetMessage[] {
  return items
    .filter(
      (item): item is { id: string; role: "user" | "assistant"; content: string } =>
        item.role === "user" || item.role === "assistant",
    )
    .map((item) => ({
      id: item.id,
      role: item.role,
      content: item.content,
      isStreaming: false,
      isError: false,
      // A resumed history row's server id IS its id -- unlike a
      // message sent live (which starts with only a client-local id
      // and gets serverId filled in later, see useChatStream.ts).
      serverId: item.id,
    }));
}

export interface UseChatWidgetResult {
  isOpen: boolean;
  toggle: () => void;
  close: () => void;
  scope: ChatScope;
  session: ChatSessionResponse | null;
  isCreatingSession: boolean;
  /** Set when session creation itself failed (e.g. 409 -- analysis not ready yet). Distinct from useChatStream's connection-level `error`. */
  sessionError: string | null;
  messages: ChatWidgetMessage[];
  connectionStatus: ChatStreamConnectionStatus;
  streamError: string | null;
  isAssistantTyping: boolean;
  sendMessage: (text: string) => void;

  // (B9) Edit a past user message -- see useChatStream.ts's editMessage.
  editMessage: (localMessageId: string, newContent: string) => Promise<boolean>;
  isEditingMessage: boolean;
  editError: string | null;

  // (B9) Conversation list -- revisit and continue a past session.
  /** True while the history panel (session list) is showing instead of the live transcript. */
  isHistoryOpen: boolean;
  toggleHistory: () => void;
  /** The caller's own past sessions, most-recently-updated first. Empty until the history panel has been opened at least once. */
  historySessions: ChatSessionResponse[];
  isLoadingHistorySessions: boolean;
  historySessionsError: string | null;
  /** Load pastSessionId's transcript and make it the active session -- closes the history panel and resumes the conversation over a fresh WS connection. */
  openHistorySession: (pastSessionId: string) => void;
  /** True while a picked session's transcript is being fetched (between openHistorySession and the resumed connection opening). */
  isResumingSession: boolean;
  /** Discards the current/resumed session and returns to normal scope-based auto-creation (e.g. after resuming an old memo-scoped chat, go back to "new conversation for this page"). */
  startNewConversation: () => void;
}

/**
 * Drive the floating AIRP Assistant widget's open/session/stream state.
 *
 * Must be called from within a component rendered under both
 * AuthProvider (useAuth) and a Router (useLocation) -- RootLayout,
 * where ChatWidget is mounted, already sits inside both.
 */
export function useChatWidget(): UseChatWidgetResult {
  const { accessToken, isAuthenticated } = useAuth();
  const location = useLocation();
  const scope = useMemo(() => deriveChatScope(location.pathname), [location.pathname]);
  const scopeKey = chatScopeKey(scope);

  const [isOpen, setIsOpen] = useState(false);
  const [session, setSession] = useState<ChatSessionResponse | null>(null);
  const [isCreatingSession, setIsCreatingSession] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);

  // Tracks the scopeKey the current `session` (if any) was created
  // for, independent of React's render cycle -- see "Why a session is
  // discarded" above. A ref (not a dependency-array trick) because the
  // reset effect below needs to compare against the PRIOR scopeKey,
  // not re-derive it.
  const sessionScopeKeyRef = useRef<string | null>(null);

  // Tracks the scopeKey a creation attempt has already been made for
  // (successful or not), so a FAILED attempt (e.g. a 409 -- analysis
  // not ready yet) does not retry itself in a tight loop: the
  // create-session effect below relies SOLELY on this ref (not on
  // `isCreatingSession` state) to guard against a second attempt for
  // the same scope -- `attemptedScopeKeyRef.current = scopeKey` is
  // set synchronously, before the async call starts, so it already
  // blocks any duplicate POST for this scope on every subsequent
  // effect run, success or failure, with no dependency on
  // `isCreatingSession` at all. This distinction matters:
  // `isCreatingSession` must NOT also be a dependency of the effect
  // that sets it -- `setIsCreatingSession(true)` is the first line
  // inside `createForCurrentScope()`, so if the effect depended on
  // `isCreatingSession`, that very state flip would re-run the effect
  // immediately (before the in-flight `fetch` has resolved), firing
  // this effect's own cleanup and setting `cancelled = true` on the
  // request that is still awaiting a response. The real result,
  // whichever way it turns out, would then be silently discarded --
  // `session`/`sessionError` never get set, and `isCreatingSession`
  // (only ever reset to false inside that same now-cancelled branch)
  // would be stuck true forever. `isCreatingSession` remains ordinary
  // state (not folded into a ref) purely because ChatWidget.tsx's UI
  // needs it to re-render a loading spinner -- it is read once, at
  // the top of `createForCurrentScope()`, to drive that render, and
  // otherwise plays no role in this effect's own guard/dependency
  // logic. Cleared whenever the scope itself changes (see the reset
  // effect), so a genuinely new scope always gets its own fresh
  // attempt; a retry for the SAME failed scope only happens if the
  // person closes and re-opens the panel (see `close`/`toggle` below
  // clearing sessionError, which does not by itself clear this ref --
  // intentionally: closing and re-opening for the same scope should
  // not hammer the backend either. A future "Retry" affordance in the
  // panel is the natural place to clear this ref on demand).
  const attemptedScopeKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (sessionScopeKeyRef.current !== null && sessionScopeKeyRef.current !== scopeKey) {
      setSession(null);
      setSessionError(null);
      attemptedScopeKeyRef.current = null;
    }
  }, [scopeKey]);

  useEffect(() => {
    if (
      !isOpen ||
      session !== null ||
      attemptedScopeKeyRef.current === scopeKey ||
      !isAuthenticated ||
      accessToken === null
    ) {
      return undefined;
    }

    let cancelled = false;
    attemptedScopeKeyRef.current = scopeKey;

    async function createForCurrentScope(): Promise<void> {
      setIsCreatingSession(true);
      setSessionError(null);
      try {
        const created = await createChatSession({
          // accessToken is narrowed non-null by the guard above, but
          // TypeScript cannot see that across the async boundary --
          // re-check here rather than a non-null assertion.
          accessToken: accessToken ?? "",
          sessionType: scope.sessionType,
          analysisId: scope.analysisId,
        });
        if (!cancelled) {
          sessionScopeKeyRef.current = scopeKey;
          setSession(created);
        }
      } catch (caught) {
        if (!cancelled) {
          setSessionError(
            caught instanceof ChatApiError
              ? caught.message
              : "Could not start a chat session. Please try again.",
          );
        }
      } finally {
        if (!cancelled) {
          setIsCreatingSession(false);
        }
      }
    }

    void createForCurrentScope();

    return (): void => {
      cancelled = true;
    };
  }, [
    isOpen,
    session,
    isAuthenticated,
    accessToken,
    scope.sessionType,
    scope.analysisId,
    scopeKey,
  ]);

  // (B9) Conversation list state -- see UseChatWidgetResult's own field
  // docstrings for what each piece means to a caller.
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [historySessions, setHistorySessions] = useState<ChatSessionResponse[]>([]);
  const [isLoadingHistorySessions, setIsLoadingHistorySessions] = useState(false);
  const [historySessionsError, setHistorySessionsError] = useState<string | null>(null);
  const [isResumingSession, setIsResumingSession] = useState(false);
  // Seeds useChatStream's transcript ONLY for the session currently
  // being resumed -- see toWidgetMessages/openHistorySession below.
  // null (the ordinary case) means useChatStream starts empty, exactly
  // as it did before B9.
  const [resumedMessages, setResumedMessages] = useState<ChatWidgetMessage[] | null>(null);
  // See openHistorySession's own "latest request wins" comment below.
  const resumeRequestIdRef = useRef(0);

  useEffect(() => {
    if (!isHistoryOpen || accessToken === null) {
      return undefined;
    }
    let cancelled = false;
    setIsLoadingHistorySessions(true);
    setHistorySessionsError(null);

    async function loadSessions(): Promise<void> {
      try {
        // accessToken narrowed non-null by the guard above; re-checked
        // here since TypeScript cannot see that across the async
        // boundary (same pattern as createForCurrentScope above).
        const page = await listChatSessions({ accessToken: accessToken ?? "" });
        if (!cancelled) {
          setHistorySessions(page.items);
        }
      } catch (caught) {
        if (!cancelled) {
          setHistorySessionsError(
            caught instanceof ChatApiError
              ? caught.message
              : "Could not load past conversations. Please try again.",
          );
        }
      } finally {
        if (!cancelled) {
          setIsLoadingHistorySessions(false);
        }
      }
    }

    void loadSessions();

    return (): void => {
      cancelled = true;
    };
  }, [isHistoryOpen, accessToken]);

  const toggleHistory = useCallback(() => {
    setIsHistoryOpen((previous) => !previous);
  }, []);

  const openHistorySession = useCallback(
    (pastSessionId: string) => {
      if (accessToken === null) {
        return;
      }
      const found = historySessions.find((entry) => entry.id === pastSessionId);
      if (found === undefined) {
        // Not in the currently-loaded page -- nothing to resume into.
        // The history panel only ever offers ids it just listed, so
        // this is defensive only (e.g. a stale click after a refetch).
        return;
      }
      // Re-bound to a definitely-ChatSessionResponse-typed const --
      // TypeScript's control-flow narrowing of `found` above does not
      // carry into the `resume` closure defined below (an async nested
      // function), so `setSession(found)` there would otherwise still
      // see `ChatSessionResponse | undefined`.
      const picked: ChatSessionResponse = found;

      // "Latest request wins" guard: openHistorySession is an
      // imperative click handler, not an effect, so there is no
      // cleanup hook to cancel an in-flight fetch if the person clicks
      // a DIFFERENT past session before the first one's fetch
      // resolves. Each call claims a fresh request id; a resolving
      // fetch only applies its result if it is still the most recent
      // one requested, so a slow, superseded fetch can never clobber a
      // later click's session/transcript.
      resumeRequestIdRef.current += 1;
      const requestId = resumeRequestIdRef.current;

      setIsResumingSession(true);
      setSessionError(null);

      async function resume(): Promise<void> {
        try {
          const page = await getChatSessionMessages({
            accessToken: accessToken ?? "",
            sessionId: pastSessionId,
            limit: HISTORY_MESSAGES_LIMIT,
          });
          if (resumeRequestIdRef.current !== requestId) {
            return;
          }
          // Make this the active session for the CURRENT route's
          // scope -- see useChatWidget's module docstring section
          // above for why a resumed session is not immediately
          // discarded by the scope-change effect: it deliberately
          // claims the current scopeKey as its own, exactly like a
          // freshly auto-created session would, and stays active
          // until the person navigates to a genuinely different scope.
          sessionScopeKeyRef.current = scopeKey;
          attemptedScopeKeyRef.current = scopeKey;
          setResumedMessages(toWidgetMessages(page.items));
          setSession(picked);
          setIsHistoryOpen(false);
        } catch (caught) {
          if (resumeRequestIdRef.current === requestId) {
            setSessionError(
              caught instanceof ChatApiError
                ? caught.message
                : "Could not load that conversation. Please try again.",
            );
          }
        } finally {
          if (resumeRequestIdRef.current === requestId) {
            setIsResumingSession(false);
          }
        }
      }

      void resume();
    },
    [accessToken, historySessions, scopeKey],
  );

  const startNewConversation = useCallback(() => {
    // Invalidate any in-flight openHistorySession fetch so it cannot
    // resurrect a resumed session after this reset.
    resumeRequestIdRef.current += 1;
    sessionScopeKeyRef.current = null;
    attemptedScopeKeyRef.current = null;
    setResumedMessages(null);
    setSession(null);
    setSessionError(null);
    setIsHistoryOpen(false);
  }, []);

  const stream = useChatStream({
    sessionId: session?.id ?? null,
    token: accessToken,
    enabled: session !== null,
    // Spread rather than `initialMessages: resumedMessages ?? undefined`
    // -- exactOptionalPropertyTypes forbids explicitly passing
    // `undefined` for an optional property, so the key is omitted
    // entirely (not set to undefined) when there is nothing to resume.
    ...(resumedMessages !== null ? { initialMessages: resumedMessages } : {}),
  });

  const toggle = useCallback(() => {
    setIsOpen((previous) => !previous);
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
  }, []);

  return {
    isOpen,
    toggle,
    close,
    scope,
    session,
    isCreatingSession,
    sessionError,
    messages: stream.messages,
    connectionStatus: stream.connectionStatus,
    streamError: stream.error,
    isAssistantTyping: stream.isAssistantTyping,
    sendMessage: stream.sendMessage,
    editMessage: stream.editMessage,
    isEditingMessage: stream.isEditingMessage,
    editError: stream.editError,
    isHistoryOpen,
    toggleHistory,
    historySessions,
    isLoadingHistorySessions,
    historySessionsError,
    openHistorySession,
    isResumingSession,
    startNewConversation,
  };
}
