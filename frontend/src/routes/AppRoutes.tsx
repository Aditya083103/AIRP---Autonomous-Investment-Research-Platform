// frontend/src/routes/AppRoutes.tsx
// The route table. A layout route with a home index (the landing page,
// T-055), a protected /analysis route (the real input form, T-058),
// /login and /register (T-056), a protected /dashboard (real history
// table, T-057) and a protected /analysis/:jobId/result placeholder
// (real results page lands in T-061), the T-054 component preview
// route, and a catch-all 404. Later Phase 6 tasks add the remaining
// real pages (compare) as nested children of RootLayout here.

import { Route, Routes } from "react-router-dom";

import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { RootLayout } from "@/components/layout/RootLayout";
import { AnalysisPage } from "@/pages/AnalysisPage";
import { AnalysisResultPage } from "@/pages/AnalysisResultPage";
import { ComponentsPreviewPage } from "@/pages/ComponentsPreviewPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { HomePage } from "@/pages/HomePage";
import { LoginPage } from "@/pages/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { RegisterPage } from "@/pages/RegisterPage";

export function AppRoutes(): JSX.Element {
  return (
    <Routes>
      <Route element={<RootLayout />}>
        <Route index element={<HomePage />} />
        <Route
          path="analysis"
          element={
            <ProtectedRoute>
              <AnalysisPage />
            </ProtectedRoute>
          }
        />
        <Route path="login" element={<LoginPage />} />
        <Route path="register" element={<RegisterPage />} />
        <Route
          path="dashboard"
          element={
            <ProtectedRoute>
              <DashboardPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="analysis/:jobId/result"
          element={
            <ProtectedRoute>
              <AnalysisResultPage />
            </ProtectedRoute>
          }
        />
        <Route path="dev/components" element={<ComponentsPreviewPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
