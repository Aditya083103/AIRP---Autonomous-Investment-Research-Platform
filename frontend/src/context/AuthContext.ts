// frontend/src/context/AuthContext.ts
// AIRP -- Auth context definition (T-056)
//
// Split from AuthProvider.tsx and useAuth.ts on purpose: this file
// exports no component, so eslint's react-refresh/only-export-components
// rule (which the frontend CI lint gate runs with --max-warnings 0) has
// nothing to warn about here. AuthProvider.tsx exports only the
// AuthProvider component; useAuth.ts exports only the useAuth hook --
// each file has a single, unmixed export kind.

import { createContext } from "react";

import { type LoginInput, type RegisterInput } from "@/api/auth";
import { type UserResponse } from "@/types/auth";

export interface AuthContextValue {
  /** The logged-in user, or null when no one is authenticated this session. */
  user: UserResponse | null;
  /** Raw JWT for Authorization headers and the WebSocket `?token=` param. */
  accessToken: string | null;
  /** True once a register/login response has been received and stored. */
  isAuthenticated: boolean;
  register: (input: RegisterInput) => Promise<void>;
  login: (input: LoginInput) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
