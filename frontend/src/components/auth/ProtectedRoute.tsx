// frontend/src/components/auth/ProtectedRoute.tsx
// AIRP -- Route guard (T-056)
//
// Wraps a route element that requires an authenticated session (first
// consumer: /dashboard). Redirects to /login when nobody is
// authenticated in this tab's AuthProvider state, passing the attempted
// location via router state so LoginPage can send the user back to
// where they were headed after a successful login instead of always
// landing on /dashboard.
//
// See src/providers/AuthProvider.tsx's module docstring for the known
// limitation this inherits: a hard page refresh clears the in-memory
// session, so refreshing a protected route currently bounces back to
// /login even though the httpOnly cookie is still present server-side.

import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";

interface ProtectedRouteProps {
  children: JSX.Element;
}

export function ProtectedRoute({ children }: ProtectedRouteProps): JSX.Element {
  const { isAuthenticated } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return children;
}
