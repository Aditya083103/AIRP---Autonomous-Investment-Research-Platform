import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],

  resolve: {
    // fileURLToPath correctly converts a file:// URL to a filesystem path on
    // every platform. `.pathname` must NOT be used here: on Windows it keeps
    // a leading slash before the drive letter (e.g. "/C:/Users/..."), which
    // Vite's resolver then concatenates onto an already-absolute Windows
    // path, producing a broken "C:\C:\Users\..." path and an ENOENT.
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@components": fileURLToPath(new URL("./src/components", import.meta.url)),
      "@hooks": fileURLToPath(new URL("./src/hooks", import.meta.url)),
      "@pages": fileURLToPath(new URL("./src/pages", import.meta.url)),
      "@api": fileURLToPath(new URL("./src/api", import.meta.url)),
      "@types": fileURLToPath(new URL("./src/types", import.meta.url)),
    },
  },

  server: {
    port: 3000,
    proxy: {
      // ws: true is required here -- the live analysis stream endpoint
      // lives at /api/v1/analysis/{job_id}/stream (see
      // backend/routers/websocket.py), which matches this /api prefix.
      // Without ws: true, Vite's dev proxy (http-proxy under the hood)
      // only forwards plain HTTP requests through this rule and never
      // upgrades the connection for a WebSocket handshake -- the
      // browser then reports "WebSocket is closed before the
      // connection is established" immediately, even though the
      // backend itself is completely healthy (confirmed: POST
      // /auth/login and POST /api/v1/analysis/start both succeed
      // through this same proxy entry, since those are plain HTTP).
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true,
      },
      // T-056: backend/routers/auth.py mounts at "/auth", not under
      // "/api/v1" (see backend/main.py's router registration), so it
      // needs its own proxy entry rather than falling under "/api" above.
      "/auth": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },

  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
