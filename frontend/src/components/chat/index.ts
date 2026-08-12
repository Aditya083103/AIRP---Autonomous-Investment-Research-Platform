// frontend/src/components/chat/index.ts
// Barrel export for the AIRP Assistant chat widget (T-105). Mirrors
// every other components/<feature>/index.ts barrel in this codebase
// (components/memo, components/results, components/charts, ...).

export { ChatWidget, type ChatWidgetProps } from "@/components/chat/ChatWidget";
export {
  ChatMessageBubble,
  type ChatMessageBubbleProps,
} from "@/components/chat/ChatMessageBubble";
