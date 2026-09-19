// frontend/src/lib/chat/chatWidgetBus.ts
// AIRP -- cross-component "open the AIRP Assistant" signal (landing-page
// redesign, AssistantPreviewSection)
//
// ChatWidget is mounted exactly once, in RootLayout, with its own
// isolated useChatWidget() state (see ChatWidget.tsx's module
// docstring) -- there is no shared context a distant component like
// AssistantPreviewSection could read to flip that widget's `isOpen`
// state directly. A plain window CustomEvent is the smallest thing that
// bridges the two without introducing a new React context purely for
// one boolean: AssistantPreviewSection's "Try the assistant" CTA
// dispatches the event, and ChatWidget listens for it (see that
// component's own listener) and opens itself if it is not already open.

export const OPEN_CHAT_WIDGET_EVENT = "airp:open-chat-widget";

/** Asks the mounted ChatWidget (if any -- only rendered for signed-in visitors) to open. */
export function requestOpenChatWidget(): void {
  window.dispatchEvent(new Event(OPEN_CHAT_WIDGET_EVENT));
}
