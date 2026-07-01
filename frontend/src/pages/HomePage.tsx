// frontend/src/pages/HomePage.tsx
// Home index route. T-053 shipped a small foundation page here, noting
// explicitly that "the marketing landing page proper is a later Phase 6
// task" -- this is that task (T-055). HomePage's own job is now just
// composition: it renders the six landing sections in reading order and
// owns none of their content, matching every later Phase 6 page's pattern
// of composing from shared building blocks (@/components/ui, and now
// @/components/landing) rather than hand-rolling markup inline.

import {
  CommitteeSection,
  DemoCtaSection,
  HeroSection,
  HowItWorksSection,
  LandingFooter,
  TechStackSection,
} from "@/components/landing";

export function HomePage(): JSX.Element {
  return (
    <div>
      <HeroSection />
      <CommitteeSection />
      <HowItWorksSection />
      <DemoCtaSection />
      <TechStackSection />
      <LandingFooter />
    </div>
  );
}
