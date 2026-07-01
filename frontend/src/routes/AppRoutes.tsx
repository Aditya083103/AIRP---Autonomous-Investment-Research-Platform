// frontend/src/routes/AppRoutes.tsx
// The route table. A layout route with a home index (the landing page,
// T-055), a placeholder /analysis route (real form lands in T-058), the
// T-054 component preview route, and a catch-all 404. Later Phase 6 tasks
// add the remaining real pages (auth, dashboard, results, compare) as
// nested children of RootLayout here.

import { Route, Routes } from "react-router-dom";

import { RootLayout } from "@/components/layout/RootLayout";
import { AnalysisPage } from "@/pages/AnalysisPage";
import { ComponentsPreviewPage } from "@/pages/ComponentsPreviewPage";
import { HomePage } from "@/pages/HomePage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export function AppRoutes(): JSX.Element {
  return (
    <Routes>
      <Route element={<RootLayout />}>
        <Route index element={<HomePage />} />
        <Route path="analysis" element={<AnalysisPage />} />
        <Route path="dev/components" element={<ComponentsPreviewPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
