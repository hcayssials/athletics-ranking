import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Static site (GitHub Pages): no backend. The data layer reads web/public/data/ — generate
// it first with `python -m scripts.build_static` (dev server and build both serve public/).
// base "./" keeps asset + data URLs relative, so the site works at any mount path
// (username.github.io/repo/, a custom domain, or a local file server).
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: { outDir: "dist" },
});
