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

  it("shows an alive agent as rate limited while model access is cooling down", () => {
    const { label, orbState } = getAgentVisualStatus(
      {
        status: "alive",
        modelAccess: {
          state: "cooling_down",
          reason: "rate_limit",
          until: 2_000_000_000,
          window: "five_hour",
        },
      },
      "idle",
      "",
      "idle",
    );
    expect(label).toMatch(/^rate limited until /);
    expect(orbState).toBe("busy");
  });
});
