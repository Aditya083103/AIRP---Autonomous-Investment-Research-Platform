// frontend/src/components/chat/ChatMessageBubble.tsx
// AIRP -- One chat transcript bubble (T-105)
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

import { TypingIndicator } from "@/components/progress/TypingIndicator";
import { type ChatWidgetMessage } from "@/hooks/useChatStream";
import { cn } from "@/lib/cn";

export interface ChatMessageBubbleProps {
  message: ChatWidgetMessage;
}

export function ChatMessageBubble({ message }: ChatMessageBubbleProps): JSX.Element {
  const isUser = message.role === "user";

  return (
    <div
      className={cn("flex w-full", isUser ? "justify-end" : "justify-start")}
      data-testid="chat-message"
      data-role={message.role}
    >
      <div
        className={cn(
          "max-w-[85%] whitespace-pre-line rounded-card px-3 py-2 text-sm leading-relaxed",
          isUser && "bg-brand-600 text-white",
          !isUser && !message.isError && "border border-line bg-canvas text-ink",
          !isUser && message.isError && "border border-verdict-sell/40 bg-canvas text-verdict-sell",
        )}
      >
        {message.content.length > 0 ? message.content : null}
        {message.isStreaming ? (
          <span className={cn(message.content.length > 0 ? "ml-2" : undefined)}>
            <TypingIndicator />
          </span>
        ) : null}
      </div>
    </div>
  );
}
