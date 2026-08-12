// frontend/src/types/chat.ts
// AIRP -- AIRP Assistant chat types (T-105)
//
// Mirrors backend.models.schemas's chat request/response models (T-103)
// field-for-field, the same "wire shape and TypeScript type stay
// identical" convention src/types/analysis.ts and src/types/accuracy.ts
// already follow -- snake_case keys on purpose, since these are the
// exact JSON keys the backend serialises, not a camelCase re-shaping.

/**
 * 'memo_scoped'    -- tied to one completed analysis (opened from
 *                     MemoPage); questions are answered using that
 *                     analysis's Investment Memo as grounded context.
 * 'portfolio_wide' -- not tied to any single analysis (opened from
 *                     anywhere else, e.g. DashboardPage); spans the
 *                     user's whole analysis history.
 */
export type ChatSessionType = "memo_scoped" | "portfolio_wide";

/** Body for POST /api/v1/chat/sessions. Mirrors ChatSessionCreateRequest. */
export interface ChatSessionCreateRequest {
  session_type: ChatSessionType;
  /** Required when session_type='memo_scoped'; omitted for 'portfolio_wide'. */
  analysis_id?: string;
  title?: string;
}

/** One chat session. Mirrors ChatSessionResponse. */
export interface ChatSessionResponse {
  id: string;
  session_type: ChatSessionType;
  analysis_id: string | null;
  title: string | null;
  created_at: string;
  updated_at: string;
}

/** One persisted message within a chat session. Mirrors ChatMessageResponse. */
export interface ChatMessageResponse {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  tool_calls: Record<string, unknown> | null;
  tool_name: string | null;
  tokens_used: number | null;
  created_at: string;
}
