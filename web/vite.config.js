import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, proxy /api to the local FastAPI (uvicorn on :8000).
// In prod the built files are served by FastAPI itself, so same-origin /api just works.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },
  build: { outDir: "dist" },
});
