import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The API the dev server proxies to. Default http://127.0.0.1:8000; override
// with LFI_API_TARGET in frontend/.env.local (gitignored) when 8000 is taken.
export default defineConfig(({ mode }) => {
  const api = loadEnv(mode, process.cwd(), "").LFI_API_TARGET || "http://127.0.0.1:8000";
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": { target: api, changeOrigin: true },
        "/ws": { target: api.replace(/^http/, "ws"), ws: true },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./tests/setup.ts"],
    },
  };
});
