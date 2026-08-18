import type {
  FullResult,
  Reporter,
  TestCase,
  TestResult,
} from "@playwright/test/reporter";
import { publishRunStatus } from "@vesta/visual/run-status";

// Publishes the web runner's phase file the way the mobile runners do: "capturing"
// once the first scenario starts, then "ready" or "error" from the run's real
// outcome, naming the failed scenarios, so the gallery's Web scan cell never reads
// a failed run as a success. A run that starts no test (`--list`) publishes nothing.
export default class RunStatusReporter implements Reporter {
  private started = false;
  private readonly failed: string[] = [];

  onTestBegin(): void {
    if (this.started) return;
    this.started = true;
    void publishRunStatus("capturing", {
      runner: "web",
      message: "Driving the web scenarios",
      startedAt: new Date().toISOString(),
    });
  }

  onTestEnd(test: TestCase, result: TestResult): void {
    if (result.status === "passed" || result.status === "skipped") return;
    this.failed.push(`${test.title} [${test.parent.project()?.name ?? "?"}]`);
  }

  async onEnd(result: FullResult): Promise<void> {
    if (!this.started) return;
    if (result.status === "passed") {
      await publishRunStatus("ready", {
        runner: "web",
        message: "Captured the web scenarios",
      });
      return;
    }
    await publishRunStatus("error", {
      runner: "web",
      message: `Web capture ${result.status}`,
      detail: this.failed.join("; "),
    });
  }
}
