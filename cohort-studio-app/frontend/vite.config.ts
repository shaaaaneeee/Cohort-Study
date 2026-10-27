/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API runs on its own port; /config.js (see public/) points
// the app at it. Production images generate /config.js at start-up instead.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  build: { sourcemap: true },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
