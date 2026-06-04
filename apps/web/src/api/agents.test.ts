import { describe, expect, it } from "vitest";
import { buildPhaseMessage, type BuildPhase } from "./agents";

describe("buildPhaseMessage", () => {
  it("maps each build phase to a distinct lowercase status line", () => {
    const phases: BuildPhase[] = [
      "pulling",
      "building",
      "preparing",
      "creating",
      "starting",
    ];
    const messages = phases.map((phase) => buildPhaseMessage(phase));
    expect(messages).toEqual([
      "downloading the agent image...",
      "building the agent image...",
      "preparing agent code...",
      "creating the container...",
      "starting up...",
    ]);
    expect(new Set(messages).size).toBe(phases.length);
    for (const message of messages) {
      expect(message).toBe(message.toLowerCase());
      expect(message).not.toContain("-");
    }
  });

  it("falls back to a neutral line when no phase is reported", () => {
    expect(buildPhaseMessage(null)).toBe("setting things up...");
  });
});
