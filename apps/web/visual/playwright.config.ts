import { defineConfig } from "@playwright/test";
import { PLATFORMS } from "@vesta/visual/platforms";

const WEB = { width: 1280, height: 800 };
const DESKTOP = { width: 1200, height: 750 };
const NARROW = { width: 420, height: 900 };
const VIEWPORTS: Record<string, { width: number; height: number }> = {
  browser: WEB,
  "desktop-window": DESKTOP,
  "phone-browser": NARROW,
};

// One project per light web platform, named by its platform id. Each test
// drives the scenario once and captures both themes: the light shot under the
// project's id, the dark one under its dark sibling.
const projects = Object.entries(PLATFORMS)
  .filter(
    ([, platform]) => platform.family === "web" && platform.theme === "light",
  )
  .map(([name, platform]) => ({
    name,
    use: {
      viewport: VIEWPORTS[platform.frame] ?? WEB,
      colorScheme: "light" as const,
    },
  }));

export default defineConfig({
  testDir: ".",
  testMatch: "capture.spec.ts",
  globalSetup: "./run-status.ts",
  globalTeardown: "./run-status-teardown.ts",
  outputDir: "../.visual/artifacts",
  reporter: [
    ["list"],
    ["html", { outputFolder: "../.visual/report", open: "never" }],
  ],
  timeout: 60000,
  fullyParallel: true,
  // 12-core host; 8 keeps headroom. A gentle scan passes --workers=2.
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
  projects,
});
