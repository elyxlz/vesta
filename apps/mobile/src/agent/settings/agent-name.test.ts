import { describe, expect, it } from "vitest";
import { agentRenameError, normalizeAgentName } from "./agent-name";

describe("normalizeAgentName", () => {
  it("matches the gateway's lowercase, separator, and character rules", () => {
    expect(normalizeAgentName("  Luna__Prime!!  ")).toBe("luna-prime");
    expect(normalizeAgentName("--luna---prime--")).toBe("luna-prime");
  });

  it("truncates to 32 characters without leaving a trailing hyphen", () => {
    expect(normalizeAgentName(`${"a".repeat(31)}-tail`)).toBe("a".repeat(31));
  });
});

describe("agentRenameError", () => {
  it("rejects an empty or canonically unchanged name", () => {
    expect(agentRenameError("luna", "!!!")).toBe("Enter a name.");
    expect(agentRenameError("luna", " LUNA ")).toBe("Choose a different name.");
  });

  it("matches the reserved-name rule while allowing the exact agent name", () => {
    expect(agentRenameError("luna", "my-vesta")).toBe(
      'Names cannot contain "vesta".',
    );
    expect(agentRenameError("luna", "vesta")).toBeNull();
  });
});
