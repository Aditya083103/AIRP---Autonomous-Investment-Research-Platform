// frontend/vitest.config.ts
// Test runner configuration (T-054). Kept as its own file rather than
// merged into vite.config.ts so the production build config stays
// untouched by test-only concerns. mergeConfig layers test settings on
// top of the real Vite config, so the same path aliases and React plugin
// vite.config.ts already defines are reused here without duplication.

import { defineConfig, mergeConfig } from "vitest/config";

import viteConfig from "./vite.config";

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      css: false,
    },
  }),
);
