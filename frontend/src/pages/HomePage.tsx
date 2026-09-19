// frontend/src/pages/HomePage.tsx
// Home index route. T-053 shipped a small foundation page here, noting
// explicitly that "the marketing landing page proper is a later Phase 6
// task" -- this is that task (T-055). HomePage's own job is composition:
// it renders the landing sections in reading order and owns none of
// their content, matching every later Phase 6 page's pattern of
// composing from shared building blocks (@/components/ui, and
// @/components/landing) rather than hand-rolling markup inline.
//
// Landing-page redesign order: AccuracyPreviewSection sits right after
// CommitteeSection -- having just met the 8 agents, "has this actually
// been right?" is the reader's next question. AssistantPreviewSection
// sits after HowItWorksSection, ahead of the final DemoCtaSection --
// introduced once the reader understands the product, as a supporting
// feature, not competing with the primary "run an analysis" CTA.
//
// A SectionDivider marks the boundary between every pair of sections
// below the hero (the hero itself needs no leading divider -- it is
// the page's own start, not a transition from something else) -- see
// that component's own docstring for why it adds no extra vertical
// space of its own.

import {
  AccuracyPreviewSection,
  AssistantPreviewSection,
  CommitteeSection,
  DemoCtaSection,
  HeroSection,
  HowItWorksSection,
  LandingFooter,
  SectionDivider,
  TechStackSection,
} from "@/components/landing";

export function HomePage(): JSX.Element {
  return (
    <div>
      <HeroSection />
      <SectionDivider />
      <CommitteeSection />
      <SectionDivider />
      <AccuracyPreviewSection />
      <SectionDivider />
      <HowItWorksSection />
      <SectionDivider />
      <AssistantPreviewSection />
      <SectionDivider />
      <DemoCtaSection />
      <SectionDivider />
      <TechStackSection />
      <LandingFooter />
    </div>
  );
}
