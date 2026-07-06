// frontend/src/providers/AppProviders.tsx
// Single composition point for every app-wide context provider. main.tsx
// renders exactly this around <App />, so adding a provider later (theme,
// auth, toaster) is a one-line change here rather than an edit to the
// entry file. Order matters: React Query sits outermost because router
// elements and the components they render both consume the query client.
// AuthProvider (T-056) sits INSIDE BrowserRouter -- ProtectedRoute and
// the login/register pages it wraps use react-router hooks
// (useNavigate/useLocation), which only work inside the Router.
//
// <ToastViewport /> (T-066) is a sibling of `children`, not a wrapper --
// it renders nothing but a fixed-position notification stack, so it has
// no children of its own to provide context to. It is placed after
// `children` in the tree (not before) purely so its fixed-position
// stacking context paints above the routed page in source order too,
// though `z-50` on the viewport itself is what actually guarantees that
// regardless of DOM order.

import { QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { BrowserRouter } from "react-router-dom";

import { ToastViewport } from "@/components/toast";
import { queryClient } from "@/lib/queryClient";
import { AuthProvider } from "@/providers/AuthProvider";

interface AppProvidersProps {
  children: ReactNode;
}

export function AppProviders({ children }: AppProvidersProps): JSX.Element {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>{children}</AuthProvider>
        <ToastViewport />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
