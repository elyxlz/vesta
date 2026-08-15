import { defineConfig } from "@playwright/test";
import type { VisualOptions } from "./test-options";

const DESKTOP = { width: 1280, height: 800 };
const NARROW = { width: 420, height: 900 };

export default defineConfig<VisualOptions>({
  testDir: ".",
  testMatch: "capture.spec.ts",
  globalSetup: "./global-setup.ts",
  outputDir: "../.visual/web/artifacts",
  timeout: 60000,
  fullyParallel: true,
  // 12-core host; 8 keeps headroom. Override with --workers on a loaded box.
  workers: 8,
  webServer: {
    command: "npm run dev",
    cwd: "..",
    url: "http://localhost:1430",
    reuseExistingServer: true,
    timeout: 60000,
    env: { HTTPS: "false" },
  },
  use: {
    baseURL: "http://localhost:1430",
    contextOptions: { reducedMotion: "reduce" },
  },
  // colorScheme mirrors the seeded app theme so surfaces that follow the OS
  // scheme (the sonner toaster) render in the same theme as the page.
  projects: [
    {
      name: "dark-desktop",
      use: { viewport: DESKTOP, theme: "dark", colorScheme: "dark" },
    },
    {
      name: "light-desktop",
      use: { viewport: DESKTOP, theme: "light", colorScheme: "light" },
    },
    {
      name: "dark-narrow",
      use: { viewport: NARROW, theme: "dark", colorScheme: "dark" },
    },
    {
      name: "light-narrow",
      use: { viewport: NARROW, theme: "light", colorScheme: "light" },
    },
  ],
});
