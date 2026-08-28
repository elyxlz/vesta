import { describe, it, expect, vi } from "vitest";
import { buildActionSections, type AgentActionsInput } from "./action-sections";

function input(overrides: Partial<AgentActionsInput>): AgentActionsInput {
  return {
    isRunning: true,
    isBusy: false,
    onLogs: vi.fn(),
    onToggle: vi.fn(),
    onRestart: vi.fn(),
    onBackup: vi.fn(),
    ...overrides,
  };
}

function itemKeys(sections: ReturnType<typeof buildActionSections>): string[] {
  return sections.flatMap((section) => section.items.map((item) => item.key));
}

describe("buildActionSections services row", () => {
  it("adds a services item in the tools section while running", () => {
    const sections = buildActionSections(input({ onServices: vi.fn() }));

    const tools = sections.find((section) => section.key === "view");
    expect(tools?.items.map((item) => item.key)).toContain("services");
  });

  it("omits the services item when no handler is given", () => {
    expect(itemKeys(buildActionSections(input({})))).not.toContain("services");
  });

  it("omits the services item while the agent is down", () => {
    const sections = buildActionSections(
      input({ isRunning: false, onServices: vi.fn() }),
    );
    expect(itemKeys(sections)).not.toContain("services");
  });
});
