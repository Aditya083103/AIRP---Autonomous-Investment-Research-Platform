// frontend/src/test/chatApi.test.ts
// Tests for src/api/chat.ts (T-105): request shape (URL, method,
// Authorization header, body) and ChatApiError message extraction --
// mirroring test/analysisApi.test.ts's approach for the same two
// FastAPI error-body shapes (string detail, and a Pydantic validation
// array with a `.msg`).

import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatApiError, createChatSession } from "@/api/chat";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const SESSION_RESPONSE = {
  id: "session-1",
  session_type: "portfolio_wide",
  analysis_id: null,
  title: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("createChatSession", () => {
  it("POSTs to /chat/sessions with the Authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, SESSION_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await createChatSession({
      accessToken: "jwt-token",
      sessionType: "portfolio_wide",
      analysisId: null,
    });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/chat/sessions");
    expect(options.method).toBe("POST");
    const headers = options.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-token");
  });

  it("sends session_type and omits analysis_id for portfolio_wide", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, SESSION_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await createChatSession({
      accessToken: "jwt-token",
      sessionType: "portfolio_wide",
      analysisId: null,
    });

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body.session_type).toBe("portfolio_wide");
    expect(body).not.toHaveProperty("analysis_id");
  });

  it("sends analysis_id when sessionType is memo_scoped", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(201, {
        ...SESSION_RESPONSE,
        session_type: "memo_scoped",
        analysis_id: "job-1",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createChatSession({
      accessToken: "jwt-token",
      sessionType: "memo_scoped",
      analysisId: "job-1",
    });

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string) as Record<string, unknown>;
    expect(body.session_type).toBe("memo_scoped");
    expect(body.analysis_id).toBe("job-1");
  });

  it("returns the parsed ChatSessionResponse on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, SESSION_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const result = await createChatSession({
      accessToken: "jwt-token",
      sessionType: "portfolio_wide",
      analysisId: null,
    });

    expect(result).toEqual(SESSION_RESPONSE);
  });

  it("throws ChatApiError with the string detail on a 409 (analysis not ready)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(409, { detail: "analysis_id=job-1 is not ready yet" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      createChatSession({
        accessToken: "jwt-token",
        sessionType: "memo_scoped",
        analysisId: "job-1",
      }),
    ).rejects.toThrow(ChatApiError);

    await expect(
      createChatSession({
        accessToken: "jwt-token",
        sessionType: "memo_scoped",
        analysisId: "job-1",
      }),
    ).rejects.toThrow("analysis_id=job-1 is not ready yet");
  });

  it("throws ChatApiError carrying the response status", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(404, { detail: "No analysis found" }));
    vi.stubGlobal("fetch", fetchMock);

    try {
      await createChatSession({
        accessToken: "jwt-token",
        sessionType: "memo_scoped",
        analysisId: "missing-job",
      });
      expect.unreachable("createChatSession should have thrown");
    } catch (error) {
      expect(error).toBeInstanceOf(ChatApiError);
      expect((error as ChatApiError).status).toBe(404);
    }
  });

  it("falls back to a generic message when the error body is not JSON", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("not json", { status: 500 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      createChatSession({
        accessToken: "jwt-token",
        sessionType: "portfolio_wide",
        analysisId: null,
      }),
    ).rejects.toThrow("Something went wrong. Please try again.");
  });
});
