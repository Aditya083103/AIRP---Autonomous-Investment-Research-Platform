// frontend/src/types/auth.ts
// TypeScript types mirroring backend.models.schemas' auth models exactly
// (T-046 / T-056) -- field names and casing (snake_case) match the JSON
// backend/routers/auth.py actually serialises, the same convention
// src/hooks/useAnalysisStream.ts already follows for AgentStreamEvent.
// Keeping the wire shape and the TypeScript type identical means a
// response can be trusted as-is without a separate camelCase remapping
// step that could silently drift from the backend schema over time.

/**
 * Mirrors backend.models.schemas.UserResponse. Returned by
 * POST /auth/register, POST /auth/login (nested under TokenResponse),
 * and GET /auth/me.
 */
export interface UserResponse {
  id: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
  created_at: string;
}

/** Mirrors backend.models.schemas.TokenResponse. */
export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in_minutes: number;
  user: UserResponse;
}
