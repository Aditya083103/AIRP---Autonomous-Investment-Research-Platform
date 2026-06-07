import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],

  resolve: {
    // URL is a DOM global (no node:url import needed). .pathname gives the
    // filesystem path from a file:// URL, which is correct on Linux/macOS CI.
    alias: {
      "@": new URL("./src", import.meta.url).pathname,
      "@components": new URL("./src/components", import.meta.url).pathname,
      "@hooks": new URL("./src/hooks", import.meta.url).pathname,
      "@pages": new URL("./src/pages", import.meta.url).pathname,
      "@api": new URL("./src/api", import.meta.url).pathname,
      "@types": new URL("./src/types", import.meta.url).pathname,
    },
  },

  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
        changeOrigin: true,
      },
    },
  },

  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
