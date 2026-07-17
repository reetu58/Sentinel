import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dashboard keeps ALL state server-side; it only talks to the API. In dev,
// proxy /api to the FastAPI backend (override with BACKEND_URL).
const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
    },
  },
});
