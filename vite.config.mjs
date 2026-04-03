import path from "node:path";
import { defineConfig } from "vite";

const ROOT_DIR = path.resolve(__dirname);

export default defineConfig({
  root: ROOT_DIR,
  appType: "custom",
  publicDir: false,
  build: {
    manifest: true,
    outDir: path.join(ROOT_DIR, "static", "dist"),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        "frontend/src/entries/login.js": path.join(ROOT_DIR, "frontend", "src", "entries", "login.js"),
        "frontend/src/entries/workspace.js": path.join(ROOT_DIR, "frontend", "src", "entries", "workspace.js"),
        "frontend/src/entries/user-center.js": path.join(ROOT_DIR, "frontend", "src", "entries", "user-center.js"),
        "frontend/src/entries/resume-report.js": path.join(ROOT_DIR, "frontend", "src", "entries", "resume-report.js"),
        "frontend/src/entries/test-result.js": path.join(ROOT_DIR, "frontend", "src", "entries", "test-result.js"),
        "frontend/src/entries/test-runner.js": path.join(ROOT_DIR, "frontend", "src", "entries", "test-runner.js")
      },
      output: {
        assetFileNames: "assets/[name]-[hash][extname]",
        chunkFileNames: "assets/[name]-[hash].js",
        entryFileNames: "assets/[name]-[hash].js"
      }
    }
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    origin: process.env.VITE_DEV_SERVER_URL || "http://127.0.0.1:5173"
  }
});
