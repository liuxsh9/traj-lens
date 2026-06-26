import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base: served at "/" standalone, or "/trajlens/" when reverse-proxied under a
// sub-path (e.g. dataview.rnd.com/trajlens/). Set VITE_BASE=/trajlens/ at build
// time for the proxied deploy; defaults to "/" so standalone is unchanged.
// All API calls go through u() in api.ts, which prefixes import.meta.env.BASE_URL.
const base = process.env.VITE_BASE || "/";

// Dev: proxy /api to the FastAPI backend so the browser sees a single origin.
export default defineConfig({
  base,
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
});
