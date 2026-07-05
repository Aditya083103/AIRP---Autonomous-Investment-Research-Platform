// frontend/src/routes/AppRoutes.tsx
// The route table. A layout route with a home index (the landing page,
// T-055), a protected /analysis route (the real input form, T-058),
// /login and /register (T-056), a protected /dashboard (real history
// table, T-057), a protected /analysis/:jobId/result (T-061) and
// /analysis/:jobId/memo (T-063), a protected /compare two-company
// comparison page (T-064), the T-054 component preview route, and a
// catch-all 404.

import { Route, Routes } from "react-router-dom";

import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { RootLayout } from "@/components/layout/RootLayout";
import { AnalysisPage } from "@/pages/AnalysisPage";
import { AnalysisResultPage } from "@/pages/AnalysisResultPage";
import { ComparePage } from "@/pages/ComparePage";
import { ComponentsPreviewPage } from "@/pages/ComponentsPreviewPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { HomePage } from "@/pages/HomePage";
import { LoginPage } from "@/pages/LoginPage";
import { MemoPage } from "@/pages/MemoPage";
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
        <Route
          path="analysis/:jobId/memo"
          element={
            <ProtectedRoute>
              <MemoPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="compare"
          element={
            <ProtectedRoute>
              <ComparePage />
            </ProtectedRoute>
          }
        />
        <Route path="dev/components" element={<ComponentsPreviewPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
