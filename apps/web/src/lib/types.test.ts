import { describe, it, expect } from "vitest";
import type { VestaEvent } from "./types";

describe("VestaEvent contract", () => {
  const EXPECTED_TYPES = [
    "status",
    "user",
    "assistant",
    "thinking",
    "chat",
    "tool_start",
    "tool_end",
    "error",
    "notification",
    "subagent_start",
    "subagent_stop",
    "history",
  ] as const;

  it("covers all expected event types", () => {
    // If VestaEvent doesn't cover a type, this won't compile
    const typeCheck: VestaEvent["type"][] = [...EXPECTED_TYPES];
    expect(typeCheck).toHaveLength(EXPECTED_TYPES.length);
  });

  // The `VestaEvent` annotation on each row is the real assertion: a missing or
  // mistyped field fails to compile. The runtime check just confirms the row ran.
  it.each<VestaEvent>([
    { type: "tool_start", tool: "Bash", input: "ls", subagent: false },
    { type: "tool_end", tool: "Bash", subagent: true },
    { type: "subagent_start", agent_id: "abc", agent_type: "browser" },
    { type: "subagent_stop", agent_id: "abc", agent_type: "browser" },
    {
      type: "history",
      events: [{ type: "user", text: "hello" }],
      state: "idle",
      cursor: null,
    },
  ])("$type satisfies the VestaEvent shape", (event) => {
    expect(event.type).toBeTruthy();
  });
});
