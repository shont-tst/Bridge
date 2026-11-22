import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// Writes dist/version.json with the VERSION from src/version.ts. The server hands it out at /api/version, so a phone
// running an older copy of the app can tell a newer one has been published and offer Reload.
function versionFile(): Plugin {
  return {
    name: "version-file",
    generateBundle() {
      const src = readFileSync(new URL("./src/version.ts", import.meta.url), "utf8");
      const version = src.match(/export const VERSION = "([^"]+)"/)?.[1];
      if (!version) throw new Error("VERSION not found in src/version.ts");
      this.emitFile({ type: "asset", fileName: "version.json", source: JSON.stringify({ version }) });
    },
  };
}

// Pyodide (Python built for the browser), for the offline engine (public/offline/worker.js): only the files it loads,
// served at /offline/pyodide/<its version>/, so a phone keeps them until Pyodide itself is updated. The engine itself
// (the server's game code) comes from the server (/offline/engine.zip).
const PYODIDE_FILES = ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"];
const pyodideDir = dirname(createRequire(import.meta.url).resolve("pyodide/package.json"));
const PYODIDE = JSON.parse(readFileSync(join(pyodideDir, "package.json"), "utf8")).version as string;

function pyodideFiles(): Plugin {
  return {
    name: "pyodide-files",
    generateBundle() {
      for (const f of PYODIDE_FILES)
        this.emitFile({ type: "asset", fileName: `offline/pyodide/${PYODIDE}/${f}`, source: readFileSync(join(pyodideDir, f)) });
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const f = req.url?.match(/^\/offline\/pyodide\/[\w.-]+\/([\w.-]+)/)?.[1];
        if (!f || !PYODIDE_FILES.includes(f)) return next();
        if (f.endsWith(".wasm")) res.setHeader("Content-Type", "application/wasm");
        res.end(readFileSync(join(pyodideDir, f)));
      });
    },
  };
}

// In development the Python server runs on :8000; the Vite dev server proxies to it.
export default defineConfig({
  plugins: [react(), versionFile(), pyodideFiles()],
  define: { __PYODIDE__: JSON.stringify(PYODIDE) },
  server: {
    host: true,
    proxy: {
      "/api": "http://localhost:8000",
      "/offline/engine.zip": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
