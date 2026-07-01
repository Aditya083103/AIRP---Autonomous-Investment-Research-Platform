// frontend/src/test/setup.ts
// Vitest setup file (T-054), loaded once before the test suite runs
// (see vitest.config.ts `setupFiles`). Two responsibilities: (1) extend
// Vitest's `expect` with jest-dom's DOM matchers (toBeInTheDocument,
// toHaveAttribute, ...) via the side-effecting import, and (2) unmount
// every rendered component after each test so one test's DOM doesn't
// leak into the next.

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
