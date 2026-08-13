// vitest/config, not vite: vite's defineConfig has no `test` key in its type,
// so `tsc -b` inside `npm run build` fails on it — and `tsc --noEmit` over src
// does NOT catch that, because this file belongs to the node tsconfig project.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
  },
  test: {
    // Node by default; the component tests opt into jsdom with a
    // `// @vitest-environment jsdom` docblock. vitest 4 removed
    // environmentMatchGlobs, and per-file is clearer anyway — the pure-logic
    // tests (measured, isValidPayload) need no DOM and stay fast without one.
    environment: "node",
  },
});
