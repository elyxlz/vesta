import { describe, it, expect } from "vitest";
import type { VestaEvent } from "./types";

describe("VestaEvent contract", () => {
  const EXPECTED_TYPES = [
    "status", "user", "assistant", "thinking", "chat",
    "tool_start", "tool_end", "error", "notification",
    "subagent_start", "subagent_stop", "history",
  ] as const;

  it("covers all expected event types", () => {
    // If VestaEvent doesn't cover a type, this won't compile
    const typeCheck: VestaEvent["type"][] = [...EXPECTED_TYPES];
    expect(typeCheck).toHaveLength(EXPECTED_TYPES.length);
  });

  it("tool_start includes subagent field", () => {
    const event: VestaEvent = { type: "tool_start", tool: "Bash", input: "ls", subagent: false };
    expect(event.type).toBe("tool_start");
  });

  it("tool_end includes subagent field", () => {
    const event: VestaEvent = { type: "tool_end", tool: "Bash", subagent: true };
    expect(event.type).toBe("tool_end");
  });

  it("subagent_start has required fields", () => {
    const event: VestaEvent = { type: "subagent_start", agent_id: "abc", agent_type: "browser" };
    expect(event.type).toBe("subagent_start");
  });

  it("subagent_stop has required fields", () => {
    const event: VestaEvent = { type: "subagent_stop", agent_id: "abc", agent_type: "browser" };
    expect(event.type).toBe("subagent_stop");
  });

  it("history event includes events array and cursor", () => {
    const event: VestaEvent = {
      type: "history",
      events: [{ type: "user", text: "hello" }],
      state: "idle",
      cursor: null,
    };
    expect(event.type).toBe("history");
  });
});
