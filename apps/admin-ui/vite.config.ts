import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Mounted at /admin/* on the MyPalace server (see design doc §5).
export default defineConfig({
  base: "/admin/",
  plugins: [react()],
  server: {
    port: 5173,
    // dev mode talks to a local MyPalace via this proxy so we don't
    // have to deal with CORS while iterating on the UI.
    proxy: {
      "/v1": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/live": "http://localhost:8000",
      "/ready": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
