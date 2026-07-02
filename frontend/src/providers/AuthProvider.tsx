// frontend/src/providers/AuthProvider.tsx
// AIRP -- Auth context provider (T-056)
//
// Holds the current user and access token in React state -- in memory
// only, never localStorage/sessionStorage. Two things are true at once
// here, and both matter:
//
// 1. The backend (backend/routers/auth.py) DOES set a real httpOnly
//    cookie on register/login, which is not readable by this file or
//    any other JavaScript -- that is the whole point of httpOnly. This
//    provider does not try to read it.
// 2. The raw access token STILL has to live somewhere JS can read it,
//    because src/hooks/useAnalysisStream.ts's WebSocket connection
//    (T-049) authenticates via a `?token=` query parameter -- browsers
//    cannot attach an Authorization header (or rely on a cookie made
//    for a different origin/path setup) to a WebSocket handshake in
//    this app's current design. So this context is that JS-visible
//    copy, scoped to the current tab's in-memory session only.
//
// Known limitation (intentional, see backend/routers/auth.py's T-056
// docstring): a hard page refresh clears this context, and there is no
// silent-restore-from-cookie step here, because that would require
// GET /auth/me to also accept the cookie, which is a deliberately
// separate, not-yet-implemented backend change. Until that lands, a
// refreshed page requires logging in again -- acceptable for this
// task's acceptance criterion (register -> login -> redirect works
// end-to-end within one SPA session), not a regression from before
// T-056 (there was no session persistence of any kind then either).

import { useCallback, useMemo, useState, type ReactNode } from "react";

import {
  loginUser,
  logoutUser,
  registerUser,
  type LoginInput,
  type RegisterInput,
} from "@/api/auth";
import { AuthContext, type AuthContextValue } from "@/context/AuthContext";
import { type TokenResponse, type UserResponse } from "@/types/auth";

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps): JSX.Element {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);

  const applyTokenResponse = useCallback((tokenResponse: TokenResponse): void => {
    setUser(tokenResponse.user);
    setAccessToken(tokenResponse.access_token);
  }, []);

  const register = useCallback(
    async (input: RegisterInput): Promise<void> => {
      const tokenResponse = await registerUser(input);
      applyTokenResponse(tokenResponse);
    },
    [applyTokenResponse],
  );

  const login = useCallback(
    async (input: LoginInput): Promise<void> => {
      const tokenResponse = await loginUser(input);
      applyTokenResponse(tokenResponse);
    },
    [applyTokenResponse],
  );

  const logout = useCallback(async (): Promise<void> => {
    // Clear local state first: the UI reflects "logged out" immediately
    // even if the network request below is slow or fails outright (the
    // cookie is a stateless-JWT convenience, not the source of truth for
    // this tab's session -- see the module docstring).
    setUser(null);
    setAccessToken(null);
    await logoutUser();
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      accessToken,
      isAuthenticated: user !== null && accessToken !== null,
      register,
      login,
      logout,
    }),
    [user, accessToken, register, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
