import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The built app is served by FastAPI at "/"; in development the API is proxied from :8000.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "dist", sourcemap: false },
});
