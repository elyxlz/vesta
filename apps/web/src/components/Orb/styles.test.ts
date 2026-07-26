import { describe, expect, it } from "vitest";

import { getAgentVisualStatus } from "./styles";

describe("getAgentVisualStatus", () => {
  it("shows a busy updating orb for a server-side rebuilding agent", () => {
    const { label, orbState } = getAgentVisualStatus(
      { status: "rebuilding", operation: null },
      "idle",
      "",
      "idle",
    );
    expect(label).toBe("updating...");
    expect(orbState).toBe("busy");
  });

  it("stops the orb when the agent is waiting on the user to sign in again", () => {
    const { label, orbState } = getAgentVisualStatus(
      { status: "not_authenticated", operation: null },
      "idle",
      "",
      "idle",
    );
    expect(label).toBe("needs you to sign in");
    expect(orbState).toBe("off");
  });

  it("stops the orb when the agent is waiting on the user to set it up", () => {
    const { label, orbState } = getAgentVisualStatus(
      { status: "unprovisioned", operation: null },
      "idle",
      "",
      "idle",
    );
    expect(label).toBe("needs to be set up");
    expect(orbState).toBe("off");
  });

  // The backup pauses the container, so the roster reports `stopped` while restic runs. This tab
  // started no operation of its own, which is exactly the case the local store cannot cover.
  it("shows a backup another client started rather than a stopped agent", () => {
    const { label, orbState } = getAgentVisualStatus(
      { status: "stopped", operation: "backing_up" },
      "idle",
      "",
      "idle",
    );
    expect(label).toBe("backing up...");
    expect(orbState).toBe("busy");
  });

  it("lets this tab's own operation win over the roster", () => {
    const { label, orbState } = getAgentVisualStatus(
      { status: "alive", operation: null },
      "stopping",
      "",
      "idle",
    );
    expect(label).toBe("stopping...");
    expect(orbState).toBe("busy");
  });

  it("keeps the stopped label distinct from the waiting-on-user labels", () => {
    const { label, orbState } = getAgentVisualStatus(
      { status: "stopped", operation: null },
      "idle",
      "",
      "idle",
    );
    expect(label).toBe("stopped");
    expect(orbState).toBe("off");
  });
});
