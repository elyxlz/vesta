import { describe, expect, it } from "vitest";

import { getAgentVisualStatus } from "./styles";

describe("getAgentVisualStatus", () => {
  it("shows a busy updating orb for a server-side rebuilding agent", () => {
    const { label, orbState } = getAgentVisualStatus(
      { status: "rebuilding" },
      "idle",
      "",
      "idle",
    );
    expect(label).toBe("updating...");
    expect(orbState).toBe("busy");
  });
});
