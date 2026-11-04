import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api is proxied to the Python_API on :8000.
// In a build, the Python_API serves frontend/dist from the same origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.OCI_API_URL ?? "http://localhost:8000", changeOrigin: true } },
  },
});
