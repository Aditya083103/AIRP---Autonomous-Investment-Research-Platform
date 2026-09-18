// frontend/src/components/chat/ChatMessageBubble.tsx
// AIRP -- One chat transcript bubble (T-105, extended B9)
//
// Split out of ChatWidget.tsx for the same reason
// src/components/debate/DebateMessageCard.tsx is split out of
// DebateViewer.tsx (T-060): the transcript container owns scrolling
// and layout, one row of markup owns "how does a single message look".
// Renders a user turn right-aligned in brand colour, an assistant turn
// left-aligned in a neutral surface, and -- for an assistant message
// still streaming -- a trailing TypingIndicator (T-059's three-dot
// affordance, already used for exactly this "the AI is composing a
// reply" state on AgentCard).
//
// B9 edit affordance: when `onEdit` is passed (ChatWidget.tsx only
// passes it for a 'user' message whose real id is already confirmed --
// see useChatStream.ts's ChatWidgetMessage.serverId), a small pencil
// button switches this bubble into an inline textarea + Save/Cancel,
// matching the "click a past message, edit it, re-run from there" UX
// Claude's own chat uses. Saving calls back with the new text and lets
// the caller (useChatWidget's editMessage) own the actual
// delete-and-resend; this component only owns the small amount of
// local "am I currently editing" UI state.

import { useState } from "react";

import { TypingIndicator } from "@/components/progress/TypingIndicator";
import { Button } from "@/components/ui";
import { type ChatWidgetMessage } from "@/hooks/useChatStream";
import { renderChatMarkdown } from "@/lib/chat/renderChatMarkdown";
import { cn } from "@/lib/cn";

function EditIcon(): JSX.Element {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-3.5 w-3.5" aria-hidden="true">
      <path
        d="M13.5 3.5 16.5 6.5M4 16l.7-3.2L12.3 5.2a1 1 0 0 1 1.4 0l1.1 1.1a1 1 0 0 1 0 1.4L7.2 15.3 4 16Z"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export interface ChatMessageBubbleProps {
  message: ChatWidgetMessage;
  /** (B9) Present only when this message can be edited right now -- renders the pencil affordance and is called with the new text on save. */
  onEdit?: (newContent: string) => void;
}

export function ChatMessageBubble({ message, onEdit }: ChatMessageBubbleProps): JSX.Element {
  const isUser = message.role === "user";
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);

  function startEditing(): void {
    setDraft(message.content);
    setIsEditing(true);
  }

  function cancelEditing(): void {
    setIsEditing(false);
  }

  function saveEditing(): void {
    const trimmed = draft.trim();
    if (trimmed.length === 0 || onEdit === undefined) {
      return;
    }
    onEdit(trimmed);
    setIsEditing(false);
  }

  if (isEditing) {
    return (
      <div className="flex w-full justify-end" data-testid="chat-message" data-role={message.role}>
        <div className="w-[85%] rounded-card border border-line bg-canvas p-2">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                saveEditing();
              } else if (event.key === "Escape") {
                cancelEditing();
              }
            }}
            rows={2}
            aria-label="Edit message"
            autoFocus
            className={cn(
              "w-full resize-none rounded-card border border-line bg-surface px-2 py-1 text-sm",
              "text-ink focus:outline-none focus:ring-2 focus:ring-brand-500",
            )}
          />
          <div className="mt-2 flex justify-end gap-2">
            <Button type="button" size="sm" variant="secondary" onClick={cancelEditing}>
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              variant="primary"
              onClick={saveEditing}
              disabled={draft.trim().length === 0}
            >
              Save
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn("flex w-full items-end gap-1", isUser ? "justify-end" : "justify-start")}
      data-testid="chat-message"
      data-role={message.role}
    >
      {isUser && onEdit !== undefined ? (
        <button
          type="button"
          aria-label="Edit message"
          onClick={startEditing}
          className={cn(
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-muted",
            "transition-colors hover:bg-line hover:text-ink focus-visible:outline-none",
            "focus-visible:ring-2 focus-visible:ring-brand-500",
          )}
        >
          <EditIcon />
        </button>
      ) : null}
      <div
        className={cn(
          "max-w-[85%] rounded-card px-3 py-2 text-sm leading-relaxed",
          isUser && "whitespace-pre-line bg-brand-600 text-white",
          !isUser && !message.isError && "border border-line bg-canvas text-ink",
          !isUser && message.isError && "border border-verdict-sell/40 bg-canvas text-verdict-sell",
        )}
      >
        {message.content.length > 0
          ? isUser
            ? message.content
            : renderChatMarkdown(message.content)
          : null}
        {message.isStreaming ? (
          <span className={cn(message.content.length > 0 ? "ml-2" : undefined)}>
            <TypingIndicator />
          </span>
        ) : null}
      </div>
    </div>
  );
}
