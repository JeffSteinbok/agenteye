import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-only: inject the API token into index.html so the HMR frontend (served by
// Vite, not the backend) can authenticate against a locally-run backend. Set the
// same value on the backend via the AGENTEYE_API_TOKEN env var. Defaults to
// "dev-token" so `npm run dev` + `AGENTEYE_API_TOKEN=dev-token <backend>` works.
const devToken = process.env.AGENTEYE_API_TOKEN || "dev-token";

export default defineConfig({
  plugins: [
    react(),
    {
      name: "inject-dev-token",
      apply: "serve",
      transformIndexHtml() {
        return [
          {
            tag: "script",
            injectTo: "head-prepend",
            children: `window.__DASHBOARD_TOKEN__=${JSON.stringify(devToken)};`,
          },
        ];
      },
    },
  ],
  build: {
    outDir: "../src/static/dist",
    emptyOutDir: true,
    sourcemap: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5112",
      "/static": "http://127.0.0.1:5112",
      "/favicon.png": "http://127.0.0.1:5112",
      "/manifest.json": "http://127.0.0.1:5112",
      "/sw.js": "http://127.0.0.1:5112",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    css: true,
  },
});
