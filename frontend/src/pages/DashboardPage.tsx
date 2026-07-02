// frontend/src/pages/DashboardPage.tsx
// AIRP -- Dashboard placeholder (T-056)
//
// The real dashboard (analysis history table, search/filter, verdict
// badges) is T-057, out of scope here. This page exists so
// register -> login -> redirect has somewhere real to land, wrapped in
// ProtectedRoute (src/routes/AppRoutes.tsx) so it also demonstrates the
// other half of the acceptance criterion: an unauthenticated visit
// redirects to /login instead of rendering. Greets the logged-in user
// by name/email specifically so the redirect is *visibly* confirmable,
// not just a blank "coming soon" notice.

import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";

export function DashboardPage(): JSX.Element {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async (): Promise<void> => {
    await logout();
    navigate("/", { replace: true });
  };

  return (
    <div className="mx-auto max-w-lg py-16 text-center">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-brand-600">Signed in</p>
      <h1 className="mt-4 font-display text-3xl font-semibold text-ink">
        Welcome, {user?.display_name ?? user?.email}.
      </h1>
      <p className="mt-4 text-sm leading-relaxed text-muted">
        Your analysis history, search, and filters land here in T-057. For now, this page confirms
        register/login -&gt; redirect worked end-to-end.
      </p>
      <Button variant="secondary" onClick={() => void handleLogout()} className="mt-8">
        Log out
      </Button>
    </div>
  );
}
