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

  it("stops the orb when the agent is waiting on the user to sign in again", () => {
    const { label, orbState } = getAgentVisualStatus(
      { status: "not_authenticated" },
      "idle",
      "",
      "idle",
    );
    expect(label).toBe("needs you to sign in");
    expect(orbState).toBe("off");
  });

  it("stops the orb when the agent is waiting on the user to set it up", () => {
    const { label, orbState } = getAgentVisualStatus(
      { status: "unprovisioned" },
      "idle",
      "",
      "idle",
    );
    expect(label).toBe("needs to be set up");
    expect(orbState).toBe("off");
  });

  it("keeps the stopped label distinct from the waiting-on-user labels", () => {
    const { label, orbState } = getAgentVisualStatus(
      { status: "stopped" },
      "idle",
      "",
      "idle",
    );
    expect(label).toBe("stopped");
    expect(orbState).toBe("off");
  });
});
