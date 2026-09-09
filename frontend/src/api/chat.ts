// frontend/src/api/chat.ts
// AIRP -- Chat API client (T-105, extended B9)
//
// Thin fetch wrapper around backend/routers/chat.py's four session
// endpoints:
//   - POST   /api/v1/chat/sessions                      (T-103) -- createChatSession
//   - GET    /api/v1/chat/sessions                       (T-103) -- listChatSessions
//   - GET    /api/v1/chat/sessions/{id}/messages         (T-103) -- getChatSessionMessages
//   - DELETE /api/v1/chat/sessions/{id}/messages/{id}    (B9)    -- deleteChatMessagesFrom
//
// listChatSessions/getChatSessionMessages were added for B9's
// conversation-list UI (see useChatWidget.ts's history state and
// ChatWidget.tsx's history panel) -- T-105 shipped only createChatSession
// and left "resuming a past session... a 'chat history' list view" as an
// explicitly documented future follow-up; this is that follow-up.
// deleteChatMessagesFrom is the client half of B9's edit-and-resend
// affordance -- see useChatStream.ts's editMessage for the full flow
// (truncate via this call, then re-send the edited text as a fresh
// turn over the existing WS connection).
//
// ChatApiError and parseErrorDetail intentionally duplicate
// src/api/analysis.ts's AnalysisApiError/parseErrorDetail rather than
// sharing one implementation -- the same tradeoff analysis.ts's and
// accuracy.ts's own docstrings already make for their own pairs.

import { env } from "@/config/env";
import {
  type ChatMessagesResponse,
  type ChatMessagesTruncateResponse,
  type ChatSessionListResponse,
  type ChatSessionResponse,
  type ChatSessionType,
} from "@/types/chat";

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

export interface ListChatSessionsParams {
  accessToken: string;
  limit?: number;
  offset?: number;
}

/**
 * GET /api/v1/chat/sessions.
 *
 * Returns the caller's own chat sessions (both memo-scoped and
 * portfolio-wide), most-recently-updated first -- see
 * ChatSessionListResponse's own docstring. Never returns another
 * user's sessions; the backend scopes strictly to the JWT's subject.
 */
export async function listChatSessions({
  accessToken,
  limit,
  offset,
}: ListChatSessionsParams): Promise<ChatSessionListResponse> {
  const params = new URLSearchParams();
  if (limit !== undefined) params.set("limit", String(limit));
  if (offset !== undefined) params.set("offset", String(offset));
  const query = params.toString();

  const response = await fetch(`${env.apiBaseUrl}/chat/sessions${query ? `?${query}` : ""}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });

  if (!response.ok) {
    throw new ChatApiError(response.status, await parseErrorDetail(response));
  }
  return (await response.json()) as ChatSessionListResponse;
}

export interface GetChatSessionMessagesParams {
  accessToken: string;
  sessionId: string;
  limit?: number;
  offset?: number;
}

/**
 * GET /api/v1/chat/sessions/{session_id}/messages.
 *
 * Returns session_id's transcript in oldest-first order. Throws a
 * ChatApiError with status 404 if session_id does not exist or belongs
 * to a different user (the backend never distinguishes the two, so
 * neither does this client).
 */
export async function getChatSessionMessages({
  accessToken,
  sessionId,
  limit,
  offset,
}: GetChatSessionMessagesParams): Promise<ChatMessagesResponse> {
  const params = new URLSearchParams();
  if (limit !== undefined) params.set("limit", String(limit));
  if (offset !== undefined) params.set("offset", String(offset));
  const query = params.toString();

  const response = await fetch(
    `${env.apiBaseUrl}/chat/sessions/${sessionId}/messages${query ? `?${query}` : ""}`,
    { headers: { Authorization: `Bearer ${accessToken}` } },
  );

  if (!response.ok) {
    throw new ChatApiError(response.status, await parseErrorDetail(response));
  }
  return (await response.json()) as ChatMessagesResponse;
}

export interface DeleteChatMessagesFromParams {
  accessToken: string;
  sessionId: string;
  /** The message to edit-from -- this message AND everything the session recorded after it are deleted. Must be a 'user' message. */
  messageId: string;
}

/**
 * DELETE /api/v1/chat/sessions/{session_id}/messages/{message_id} (B9).
 *
 * Server-side half of editing a past message: deletes message_id and
 * every message recorded after it, so the caller can then re-send the
 * edited text as a fresh turn over the existing WS connection -- see
 * useChatStream.ts's editMessage. Throws a ChatApiError with status
 * 404 if the session or message does not exist (or is not the
 * caller's), or 422 if message_id is not a 'user' message.
 */
export async function deleteChatMessagesFrom({
  accessToken,
  sessionId,
  messageId,
}: DeleteChatMessagesFromParams): Promise<ChatMessagesTruncateResponse> {
  const response = await fetch(
    `${env.apiBaseUrl}/chat/sessions/${sessionId}/messages/${messageId}`,
    {
      method: "DELETE",
      headers: { Authorization: `Bearer ${accessToken}` },
    },
  );

  if (!response.ok) {
    throw new ChatApiError(response.status, await parseErrorDetail(response));
  }
  return (await response.json()) as ChatMessagesTruncateResponse;
}
