import { readFileSync, writeFileSync, mkdirSync } from "fs";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import basicSsl from "@vitejs/plugin-basic-ssl";
import { defineConfig, type Plugin } from "vite";
import path from "path";

const host = process.env.TAURI_DEV_HOST;
const vestad = process.env.VITE_VESTAD_URL || "https://localhost:7860";

const isTauri = !!process.env.TAURI_ENV_PLATFORM;
const useHttps = !isTauri && process.env.HTTPS !== "false";

const pkg = JSON.parse(
  readFileSync(path.resolve(__dirname, "package.json"), "utf-8"),
);
const version = pkg.version;

function installScriptsPlugin(): Plugin {
  return {
    name: "generate-install-scripts",
    writeBundle(options) {
      const outDir = options.dir ?? "dist";
      mkdirSync(outDir, { recursive: true });

      writeFileSync(
        path.join(outDir, "install.sh"),
        `#!/usr/bin/env bash\nset -euo pipefail\nexec bash -c "$(curl -fsSL https://raw.githubusercontent.com/elyxlz/vesta/v${version}/install.sh)" -- --app "$@"\n`,
      );

      writeFileSync(
        path.join(outDir, "install.ps1"),
        `$ErrorActionPreference = 'Stop'\nInvoke-Expression (Invoke-RestMethod 'https://raw.githubusercontent.com/elyxlz/vesta/v${version}/install.ps1')\n`,
      );
    },
  };
}

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  plugins: [
    react({
      babel: {
        plugins: [["babel-plugin-react-compiler"]],
      },
    }),
    tailwindcss(),
    ...(useHttps ? [basicSsl()] : []),
    installScriptsPlugin(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "motion-plus-dom": path.resolve(
        __dirname,
        "./src/lib/motion-plus-dom/dist/es/index.mjs",
      ),
    },
  },
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || "0.0.0.0",
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    proxy: host
      ? undefined
      : {
          "/agents": {
            target: vestad,
            secure: false,
            ws: true,
            changeOrigin: true,
          },
          "/health": { target: vestad, secure: false, changeOrigin: true },
          "/version": { target: vestad, secure: false, changeOrigin: true },
          "/tunnel": { target: vestad, secure: false, changeOrigin: true },
        },
  },
});
