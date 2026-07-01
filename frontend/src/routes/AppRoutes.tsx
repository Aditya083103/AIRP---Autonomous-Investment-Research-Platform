// frontend/src/routes/AppRoutes.tsx
// The route table. A single layout route with a home index, the T-054
// component preview route, and a catch-all 404. Phase 6 tasks add the
// real pages (auth, dashboard, analysis, results, compare) as nested
// children of RootLayout here.

import { Route, Routes } from "react-router-dom";

import { RootLayout } from "@/components/layout/RootLayout";
import { ComponentsPreviewPage } from "@/pages/ComponentsPreviewPage";
import { HomePage } from "@/pages/HomePage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export function AppRoutes(): JSX.Element {
  return (
    <Routes>
      <Route element={<RootLayout />}>
        <Route index element={<HomePage />} />
        <Route path="dev/components" element={<ComponentsPreviewPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
