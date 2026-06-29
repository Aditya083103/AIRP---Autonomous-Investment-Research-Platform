// frontend/src/providers/AppProviders.tsx
// Single composition point for every app-wide context provider. main.tsx
// renders exactly this around <App />, so adding a provider later (theme,
// auth, toaster) is a one-line change here rather than an edit to the
// entry file. Order matters: React Query sits outermost because router
// elements and the components they render both consume the query client.

import { QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { BrowserRouter } from "react-router-dom";

import { queryClient } from "@/lib/queryClient";

interface AppProvidersProps {
  children: ReactNode;
}

export function AppProviders({ children }: AppProvidersProps): JSX.Element {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
}
