import { readFileSync, writeFileSync, mkdirSync } from "fs";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import basicSsl from "@vitejs/plugin-basic-ssl";
import { defineConfig } from "vitest/config";
import type { Plugin } from "vite";
import path from "path";

// Set by apps/desktop/scripts/dev.mjs: plain http on a fixed port so the
// Electron dev window can load it.
const desktopDev = process.env.VESTA_DESKTOP_DEV === "1";
const useHttps = !desktopDev && process.env.HTTPS !== "false";

// vestad mounts the bundled SPA at /app/. Anything else (vite dev, the
// desktop app, self-hosted) serves from the root.
const vestadHosted = process.env.VITE_VESTAD_HOSTED === "true";

const cargoToml = readFileSync(
  path.resolve(__dirname, "..", "..", "vestad", "Cargo.toml"),
  "utf-8",
);
const versionMatch = /\[package\][^[]*?\nversion\s*=\s*"([^"]+)"/.exec(
  cargoToml,
);
const versionCapture = versionMatch?.[1];
if (versionCapture === undefined) {
  throw new Error(
    "could not read [package] version from ../../vestad/Cargo.toml",
  );
}
const version: string = versionCapture;

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
  base: vestadHosted ? "/app/" : "/",
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  plugins: [
    react(),
    tailwindcss(),
    ...(useHttps ? [basicSsl()] : []),
    installScriptsPlugin(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    projects: [
      {
        extends: true,
        test: {
          include: ["src/**/*.test.tsx"],
          environment: "jsdom",
          setupFiles: ["./src/vitest.setup.ts"],
        },
      },
      {
        extends: true,
        test: {
          include: ["src/**/*.test.ts"],
          environment: "node",
        },
      },
    ],
  },
  clearScreen: false,
  server: {
    port: desktopDev ? 1420 : 1430,
    strictPort: true,
    host: "0.0.0.0",
  },
});
