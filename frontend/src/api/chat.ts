// frontend/src/api/chat.ts
// AIRP -- Chat API client (T-105)
//
// Thin fetch wrapper around backend/routers/chat.py's session-creation
// endpoint:
//   - POST /api/v1/chat/sessions (T-103) -- createChatSession
//
// Only session creation lives here. ChatWidget.tsx (this task) reads and
// writes a session's transcript exclusively over
// WS /api/v1/chat/{session_id}/stream (T-104, see src/hooks/useChatStream.ts)
// once the session exists -- GET /api/v1/chat/sessions and
// GET /api/v1/chat/sessions/{id}/messages (T-103's other two endpoints)
// have no caller yet in this task's scope (resuming a past session
// across page reloads, or a "chat history" list view, is a natural
// follow-up but not part of T-105's acceptance criteria: "widget
// available on Dashboard and MemoPage; correctly scopes questions to
// current analysis when opened from a memo").
//
// ChatApiError and parseErrorDetail intentionally duplicate
// src/api/analysis.ts's AnalysisApiError/parseErrorDetail rather than
// sharing one implementation -- the same tradeoff analysis.ts's and
// accuracy.ts's own docstrings already make for their own pairs.

import { env } from "@/config/env";
import { type ChatSessionResponse, type ChatSessionType } from "@/types/chat";

export class ChatApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ChatApiError";
    this.status = status;
  }
}

interface ValidationErrorDetail {
  msg?: string;
}

function isValidationErrorDetail(value: unknown): value is ValidationErrorDetail {
  return typeof value === "object" && value !== null;
}

/** See src/api/auth.ts's parseErrorDetail for the two FastAPI error-body shapes handled here. */
async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") {
        return detail;
      }
      if (Array.isArray(detail) && detail.length > 0 && isValidationErrorDetail(detail[0])) {
        const first = detail[0];
        if (typeof first.msg === "string") {
          return first.msg;
        }
      }
    }
  } catch {
    // Response body was not JSON -- fall through to the generic message.
  }
  return "Something went wrong. Please try again.";
}

export interface CreateChatSessionParams {
  /** Bearer token from useAuth().accessToken. Callers must not call this with a null token. */
  accessToken: string;
  sessionType: ChatSessionType;
  /** Required and must be a completed analysis the caller owns when sessionType is 'memo_scoped'. */
  analysisId?: string | null;
  title?: string;
}

/**
 * POST /api/v1/chat/sessions.
 *
 * Returns 404 (analysis not found / not owned) or 409 (analysis not
 * finished yet) as a ChatApiError with the matching `status` when
 * `sessionType === "memo_scoped"` and `analysisId` fails backend
 * validation -- callers (useChatWidget) surface `.message` directly
 * rather than branching on `.status`, since both cases already carry a
 * complete, user-readable explanation from the backend.
 */
export async function createChatSession({
  accessToken,
  sessionType,
  analysisId,
  title,
}: CreateChatSessionParams): Promise<ChatSessionResponse> {
  const response = await fetch(`${env.apiBaseUrl}/chat/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({
      session_type: sessionType,
      ...(analysisId !== null && analysisId !== undefined ? { analysis_id: analysisId } : {}),
      ...(title !== undefined ? { title } : {}),
    }),
  });

  if (!response.ok) {
    throw new ChatApiError(response.status, await parseErrorDetail(response));
  }
  return (await response.json()) as ChatSessionResponse;
}
