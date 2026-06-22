import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy /api to the FastAPI backend so the browser sees a single origin.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
});
