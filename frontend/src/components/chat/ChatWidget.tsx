// frontend/src/components/chat/ChatWidget.tsx
// AIRP -- Floating AIRP Assistant chat widget (T-105)
//
// A collapsed round toggle button, fixed to the bottom-right corner of
// the viewport, that expands into a chat panel on click. Mounted once
// in RootLayout.tsx (T-053's app shell) so it is present on every
// authenticated route without any individual page needing to render
// it -- this is what satisfies T-105's acceptance criterion "widget
// available on Dashboard and MemoPage" without touching either of
// those already-shipped, already-tested page files.
//
// All state (open/closed, which scope, session creation, the live
// token stream) lives in useChatWidget.ts -- this component is
// markup/interaction only: it reads that hook's result and renders it,
// plus owns the one piece of state that is genuinely presentational
// (the composer's current draft text, `draft` below).
//
// Rendering gate: this component returns null entirely when the
// caller is not signed in (RootLayout only mounts <ChatWidget /> when
// isAuthenticated -- see RootLayout.tsx). Session creation requires a
// JWT (backend/routers/chat.py's create_chat_session_endpoint is
// Depends(get_current_user)), so there is nothing this widget could
// usefully do for a signed-out visitor.
//
// Auto-scroll: the transcript scrolls to its latest message whenever
// `messages` changes (new turn, or another token appended to a
// streaming reply) -- the same "keep the newest content in view"
// behaviour any chat UI needs, implemented with a plain ref + a
// useEffect keyed on `messages`, not a library.

import { useEffect, useRef, useState, type FormEvent } from "react";

import { ChatMessageBubble } from "@/components/chat/ChatMessageBubble";
import { TypingIndicator } from "@/components/progress/TypingIndicator";
import { Button, Spinner } from "@/components/ui";
import { useChatWidget } from "@/hooks/useChatWidget";
import { cn } from "@/lib/cn";

const SCOPE_LABEL: Record<"memo_scoped" | "portfolio_wide", string> = {
  memo_scoped: "Asking about this memo",
  portfolio_wide: "Asking about your portfolio",
};

function ChatBubbleIcon(): JSX.Element {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-6 w-6" aria-hidden="true">
      <path
        d="M3 5.5A1.5 1.5 0 0 1 4.5 4h11A1.5 1.5 0 0 1 17 5.5v7A1.5 1.5 0 0 1 15.5 14H8l-3.5 3v-3h-1A1.5 1.5 0 0 1 2 12.5v-7Z"
        fill="currentColor"
      />
    </svg>
  );
}

function CloseIcon(): JSX.Element {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-5 w-5" aria-hidden="true">
      <path
        d="M5 5l10 10M15 5L5 15"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function SendIcon(): JSX.Element {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4" aria-hidden="true">
      <path
        d="M17 3 9 11M17 3l-5.5 14-2.7-6.3L3 8.5 17 3Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** (B9) Clock-with-arrow "history" glyph -- opens the conversation list. */
function HistoryIcon(): JSX.Element {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4" aria-hidden="true">
      <path
        d="M10 5.5V10l3 2M17 10a7 7 0 1 1-2.1-5M17 3.5V7h-3.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** (B9) Plus-in-bubble "new conversation" glyph. */
function NewChatIcon(): JSX.Element {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4" aria-hidden="true">
      <path d="M10 7v6M7 10h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path
        d="M3 5.5A1.5 1.5 0 0 1 4.5 4h11A1.5 1.5 0 0 1 17 5.5v7A1.5 1.5 0 0 1 15.5 14H8l-3.5 3v-3h-1A1.5 1.5 0 0 1 2 12.5v-7Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** (B9) Formats a ChatSessionResponse's updated_at as a short relative label ("just now", "5m ago", "3h ago", "12d ago"), falling back to a plain date once it is old enough that relative phrasing stops being useful. */
function formatRelativeTime(isoTimestamp: string): string {
  const then = new Date(isoTimestamp).getTime();
  if (Number.isNaN(then)) {
    return "";
  }
  const diffSeconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (diffSeconds < 60) return "just now";
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 30) return `${diffDays}d ago`;
  return new Date(isoTimestamp).toLocaleDateString();
}

export interface ChatWidgetProps {
  /** Overridable for tests; RootLayout does not pass this -- see the module docstring's "rendering gate" note. */
  enabled?: boolean;
}

export function ChatWidget({ enabled = true }: ChatWidgetProps): JSX.Element | null {
  const widget = useChatWidget();
  const [draft, setDraft] = useState("");
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = transcriptRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [widget.messages]);

  if (!enabled) {
    return null;
  }

  const canSend =
    !widget.isHistoryOpen &&
    widget.session !== null &&
    widget.connectionStatus === "open" &&
    !widget.isAssistantTyping &&
    draft.trim().length > 0;

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!canSend) {
      return;
    }
    widget.sendMessage(draft);
    setDraft("");
  }

  return (
    <div className="fixed bottom-6 right-6 z-40 flex flex-col items-end gap-3">
      {widget.isOpen ? (
        <div
          role="dialog"
          aria-label="AIRP Assistant chat"
          data-testid="chat-widget-panel"
          className={cn(
            "flex h-[28rem] w-[22rem] flex-col overflow-hidden rounded-card border border-line",
            "bg-surface shadow-card",
          )}
        >
          <header className="flex items-center justify-between border-b border-line bg-canvas px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-ink">AIRP Assistant</p>
              <p className="text-xs text-muted">
                {widget.isHistoryOpen
                  ? "Past conversations"
                  : SCOPE_LABEL[widget.scope.sessionType]}
              </p>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                aria-label="Start a new conversation"
                onClick={widget.startNewConversation}
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-full text-muted",
                  "transition-colors hover:bg-line hover:text-ink focus-visible:outline-none",
                  "focus-visible:ring-2 focus-visible:ring-brand-500",
                )}
              >
                <NewChatIcon />
              </button>
              <button
                type="button"
                aria-label={
                  widget.isHistoryOpen ? "Back to conversation" : "View past conversations"
                }
                aria-pressed={widget.isHistoryOpen}
                onClick={widget.toggleHistory}
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-full text-muted",
                  "transition-colors hover:bg-line hover:text-ink focus-visible:outline-none",
                  "focus-visible:ring-2 focus-visible:ring-brand-500",
                  widget.isHistoryOpen && "bg-line text-ink",
                )}
              >
                <HistoryIcon />
              </button>
              <button
                type="button"
                aria-label="Minimize AIRP Assistant chat"
                onClick={widget.close}
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-full text-muted",
                  "transition-colors hover:bg-line hover:text-ink focus-visible:outline-none",
                  "focus-visible:ring-2 focus-visible:ring-brand-500",
                )}
              >
                <CloseIcon />
              </button>
            </div>
          </header>

          {widget.isHistoryOpen ? (
            <div
              className="flex-1 space-y-1 overflow-y-auto px-3 py-3"
              data-testid="chat-history-panel"
            >
              {widget.isLoadingHistorySessions ? (
                <div className="flex items-center gap-2 px-1 py-2 text-sm text-muted" role="status">
                  <Spinner size="sm" aria-hidden="true" />
                  Loading past conversations…
                </div>
              ) : null}

              {widget.historySessionsError ? (
                <p className="px-1 py-2 text-sm text-verdict-sell" role="alert">
                  {widget.historySessionsError}
                </p>
              ) : null}

              {!widget.isLoadingHistorySessions &&
              widget.historySessionsError === null &&
              widget.historySessions.length === 0 ? (
                <p className="px-1 py-2 text-sm text-muted">
                  No past conversations yet -- start one below.
                </p>
              ) : null}

              {widget.historySessions.map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  onClick={() => widget.openHistorySession(entry.id)}
                  disabled={widget.isResumingSession}
                  className={cn(
                    "flex w-full flex-col items-start gap-0.5 rounded-card px-3 py-2 text-left",
                    "transition-colors hover:bg-line focus-visible:outline-none",
                    "focus-visible:ring-2 focus-visible:ring-brand-500 disabled:cursor-not-allowed disabled:opacity-60",
                  )}
                >
                  <span className="w-full truncate text-sm text-ink">
                    {entry.title ?? SCOPE_LABEL[entry.session_type]}
                  </span>
                  <span className="text-xs text-muted">
                    {SCOPE_LABEL[entry.session_type]} · {formatRelativeTime(entry.updated_at)}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <div ref={transcriptRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
              {widget.isCreatingSession || widget.isResumingSession ? (
                <div className="flex items-center gap-2 text-sm text-muted" role="status">
                  <Spinner size="sm" aria-hidden="true" />
                  {widget.isResumingSession
                    ? "Loading conversation…"
                    : "Starting a new conversation…"}
                </div>
              ) : null}

              {widget.sessionError ? (
                <p className="text-sm text-verdict-sell" role="alert">
                  {widget.sessionError}
                </p>
              ) : null}

              {widget.streamError ? (
                <p className="text-xs text-muted" role="alert">
                  {widget.streamError}
                </p>
              ) : null}

              {widget.editError ? (
                <p className="text-xs text-verdict-sell" role="alert">
                  {widget.editError}
                </p>
              ) : null}

              {widget.messages.length === 0 &&
              !widget.isCreatingSession &&
              !widget.isResumingSession &&
              widget.sessionError === null ? (
                <p className="text-sm text-muted">
                  {widget.scope.sessionType === "memo_scoped"
                    ? "Ask a question about this Investment Memo -- the verdict, a specific risk, or the numbers behind it."
                    : "Ask a question about your past analyses -- the AIRP Assistant can look across your whole history."}
                </p>
              ) : null}

              {widget.messages.map((message) => {
                const canEdit =
                  message.role === "user" &&
                  message.serverId !== null &&
                  !widget.isAssistantTyping &&
                  !widget.isEditingMessage;
                return (
                  <ChatMessageBubble
                    key={message.id}
                    message={message}
                    {...(canEdit
                      ? {
                          onEdit: (newContent: string) => {
                            void widget.editMessage(message.id, newContent);
                          },
                        }
                      : {})}
                  />
                );
              })}
            </div>
          )}

          <form onSubmit={handleSubmit} className="border-t border-line px-3 py-3">
            <div className="flex items-end gap-2">
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
                rows={2}
                placeholder={
                  widget.session === null ? "Starting conversation…" : "Ask the AIRP Assistant…"
                }
                aria-label="Message the AIRP Assistant"
                disabled={widget.session === null || widget.isHistoryOpen}
                className={cn(
                  "flex-1 resize-none rounded-card border border-line bg-canvas px-3 py-2 text-sm",
                  "text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-brand-500",
                  "disabled:cursor-not-allowed disabled:opacity-60",
                )}
              />
              <Button
                type="submit"
                size="sm"
                variant="primary"
                aria-label="Send message"
                disabled={!canSend}
                trailingIcon={widget.isAssistantTyping ? undefined : <SendIcon />}
              >
                {widget.isAssistantTyping ? <TypingIndicator /> : "Send"}
              </Button>
            </div>
          </form>
        </div>
      ) : null}

      <button
        type="button"
        aria-label={widget.isOpen ? "Close AIRP Assistant chat" : "Open AIRP Assistant chat"}
        aria-expanded={widget.isOpen}
        onClick={widget.toggle}
        data-testid="chat-widget-toggle"
        className={cn(
          "flex h-14 w-14 items-center justify-center rounded-full bg-brand-600 text-white shadow-card",
          "transition-colors hover:bg-brand-700 focus-visible:outline-none focus-visible:ring-2",
          "focus-visible:ring-brand-500 focus-visible:ring-offset-2",
        )}
      >
        {widget.isOpen ? <CloseIcon /> : <ChatBubbleIcon />}
      </button>
    </div>
  );
}
