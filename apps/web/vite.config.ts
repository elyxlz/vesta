import { readFileSync, writeFileSync, mkdirSync, existsSync } from "fs";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import basicSsl from "@vitejs/plugin-basic-ssl";
import { defineConfig, type Plugin } from "vite";
import path from "path";

function resolveInNodeModules(pkgRelPath: string): string {
  let dir = __dirname;
  while (true) {
    const candidate = path.join(dir, "node_modules", pkgRelPath);
    if (existsSync(candidate)) return candidate;
    const parent = path.dirname(dir);
    if (parent === dir) {
      throw new Error(
        `could not find node_modules/${pkgRelPath} walking up from ${__dirname}`,
      );
    }
    dir = parent;
  }
}
const motionPlusDomEntry = resolveInNodeModules(
  "motion-plus-dom/dist/es/index.mjs",
);

const host = process.env.TAURI_DEV_HOST;
const vestad = process.env.VITE_VESTAD_URL || "https://localhost:7860";

const isTauri = !!process.env.TAURI_ENV_PLATFORM;
const useHttps = !isTauri && process.env.HTTPS !== "false";

const cargoToml = readFileSync(
  path.resolve(__dirname, "..", "..", "vestad", "Cargo.toml"),
  "utf-8",
);
const versionMatch = cargoToml.match(
  /\[package\][^[]*?\nversion\s*=\s*"([^"]+)"/,
);
if (!versionMatch) {
  throw new Error(
    "could not read [package] version from ../../vestad/Cargo.toml",
  );
}
const version = versionMatch[1];

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
  base: isTauri ? "/" : "/app/",
  define: {
    __APP_VERSION__: JSON.stringify(version),
    __TAURI__: JSON.stringify(isTauri),
    __PLATFORM__: JSON.stringify(process.env.TAURI_ENV_PLATFORM || ""),
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
      "motion-plus-dom": motionPlusDomEntry,
    },
  },
  clearScreen: false,
  server: {
    port: isTauri ? 1420 : 1430,
    strictPort: true,
    host: host || "0.0.0.0",
    hmr: host
      ? { protocol: "ws", host, port: isTauri ? 1421 : 1431 }
      : undefined,
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
