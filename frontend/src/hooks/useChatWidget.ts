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

import { ChatApiError, createChatSession } from "@/api/chat";
import { useAuth } from "@/hooks/useAuth";
import {
  useChatStream,
  type ChatStreamConnectionStatus,
  type ChatWidgetMessage,
} from "@/hooks/useChatStream";
import { chatScopeKey, deriveChatScope, type ChatScope } from "@/lib/chat/chatScope";
import { type ChatSessionResponse } from "@/types/chat";

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
  // create-session effect below depends on `isCreatingSession` (so a
  // second open() while already creating is a safe no-op rather than
  // a duplicate POST), and that same dependency would otherwise cause
  // the effect to re-fire the instant `isCreatingSession` flips back
  // to false after a failure, with every other guard condition
  // (isOpen, session === null, isAuthenticated, accessToken) still
  // true -- an unbounded retry loop hitting the backend on every
  // render. Cleared whenever the scope itself changes (see the reset
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
      isCreatingSession ||
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
    isCreatingSession,
    isAuthenticated,
    accessToken,
    scope.sessionType,
    scope.analysisId,
    scopeKey,
  ]);

  const stream = useChatStream({
    sessionId: session?.id ?? null,
    token: accessToken,
    enabled: session !== null,
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
  };
}
