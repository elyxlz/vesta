import { publishRunStatus } from "@vesta/visual/run-status";

export default async function globalTeardown(): Promise<void> {
  await publishRunStatus("ready", {
    runner: "web",
    message: "Captured the web scenarios",
  });
}
