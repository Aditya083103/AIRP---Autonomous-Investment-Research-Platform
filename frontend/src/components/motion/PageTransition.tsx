// frontend/src/components/motion/PageTransition.tsx
// AIRP -- route transition wrapper (B10)
//
// Mounted once in RootLayout.tsx in place of a bare <Outlet />. Keys a
// motion.div on the current pathname so React remounts (and therefore
// re-animates) it on every route change, fading and rising the new
// page's content in. Deliberately entrance-only -- no AnimatePresence /
// exit animation: an exit-then-enter sequence (AnimatePresence
// mode="wait") adds a real, user-perceptible delay (the outgoing page's
// exit transition has to finish before the incoming one starts) for a
// polish effect the work order asks to be "snappy, never janky"; a
// same-duration entrance-only fade reads as an equally smooth
// transition without that cost, and never risks a test that navigates
// and immediately asserts on the new route's content racing an
// in-flight exit animation.
//
// Renders a bare <Outlet /> under usePrefersReducedMotion(), per the
// work order's explicit accessibility constraint.

import { motion } from "framer-motion";
import { Outlet, useLocation } from "react-router-dom";

import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";

const DURATION_SECONDS = 0.25;
const RISE_PIXELS = 8;

/** Fades and rises each route's content in on navigation. A bare Outlet under reduced motion. */
export function PageTransition(): JSX.Element {
  const location = useLocation();
  const prefersReducedMotion = usePrefersReducedMotion();

  if (prefersReducedMotion) {
    return <Outlet />;
  }

  return (
    <motion.div
      key={location.pathname}
      initial={{ opacity: 0, y: RISE_PIXELS }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: DURATION_SECONDS, ease: "easeOut" }}
    >
      <Outlet />
    </motion.div>
  );
}
