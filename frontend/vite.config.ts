/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `make web-dev`: Vite on http://localhost:5173, /api proxied to the backend (docker `backend` on :8000 by
// default; API_PROXY_TARGET=http://localhost:8001 for `make api-dev`). In docker, nginx does the same proxying.
const apiTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: apiTarget, changeOrigin: true } },
  },
  preview: {
    port: 4173,
    proxy: { "/api": { target: apiTarget, changeOrigin: true } },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    chunkSizeWarningLimit: 900,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    restoreMocks: true,
  },
});
