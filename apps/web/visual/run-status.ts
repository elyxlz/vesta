import { publishRunStatus } from "@vesta/visual/run-status";

// Playwright calls this file's default export once before the run: the Web scan
// cell in the gallery reads the phase like the mobile ones. run-status-teardown.ts
// publishes the end.
export default async function globalSetup(): Promise<void> {
  await publishRunStatus("capturing", {
    runner: "web",
    message: "Driving the web scenarios",
    startedAt: new Date().toISOString(),
  });
}
