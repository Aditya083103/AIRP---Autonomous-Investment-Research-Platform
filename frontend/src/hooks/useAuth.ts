// frontend/src/hooks/useAuth.ts
// AIRP -- useAuth hook (T-056)
//
// The only supported way for a component to read auth state or call
// register/login/logout -- consumes src/context/AuthContext.ts, which
// src/providers/AuthProvider.tsx (mounted in AppProviders) supplies a
// real value for. Throws instead of silently returning a fallback: a
// component rendered outside AuthProvider is a wiring bug, and failing
// loudly at the call site is far easier to debug than a mysteriously
// `null` user three components downstream.

import { useContext } from "react";

import { AuthContext, type AuthContextValue } from "@/context/AuthContext";

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
