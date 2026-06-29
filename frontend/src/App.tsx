// frontend/src/App.tsx
// Root application component. Providers live in AppProviders (rendered by
// main.tsx), so App's only job is to mount the route tree. Keeping App
// free of provider wiring means routes can be unit-tested in isolation in
// later Phase 6 tasks by rendering <App /> inside a test-specific provider.

import { AppRoutes } from "@/routes/AppRoutes";

function App(): JSX.Element {
  return <AppRoutes />;
}

export default App;
