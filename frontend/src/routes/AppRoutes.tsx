// frontend/src/routes/AppRoutes.tsx
// The route table. Kept deliberately small for T-053 (setup): a single
// layout route with a home index and a catch-all 404. Phase 6 tasks add
// the real pages (auth, dashboard, analysis, results, compare) as nested
// children of RootLayout here.

import { Route, Routes } from "react-router-dom";

import { RootLayout } from "@/components/layout/RootLayout";
import { HomePage } from "@/pages/HomePage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export function AppRoutes(): JSX.Element {
  return (
    <Routes>
      <Route element={<RootLayout />}>
        <Route index element={<HomePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
