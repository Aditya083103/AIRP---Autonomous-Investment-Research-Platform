// frontend/src/App.tsx
// Root application component. Providers live in AppProviders (rendered by
// main.tsx), so App's only job is to mount the route tree. Keeping App
// free of provider wiring means routes can be unit-tested in isolation in
// later Phase 6 tasks by rendering <App /> inside a test-specific provider.
//
// T-066 wraps <AppRoutes /> in <RootErrorBoundary> here rather than in
// AppProviders.tsx: RootErrorBoundary needs `useLocation()` (to reset the
// caught error on route change -- see ErrorBoundary.tsx's docstring), which
// only works below AppProviders' <BrowserRouter>. App.tsx is exactly that
// "inside the Router, above the routes" spot -- the same reasoning
// AuthProvider already follows for needing to sit inside BrowserRouter too.

import { RootErrorBoundary } from "@/components/error";
import { AppRoutes } from "@/routes/AppRoutes";

function App(): JSX.Element {
  return (
    <RootErrorBoundary>
      <AppRoutes />
    </RootErrorBoundary>
  );
}

export default App;
