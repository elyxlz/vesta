import { describe, expect, it } from "vitest";

import { getAgentVisualStatus } from "./styles";

describe("getAgentVisualStatus", () => {
  // The backup pauses the container, so the roster reports `stopped` while restic runs. A tab that
  // started no operation of its own is exactly the case the local store cannot cover, so the roster
  // operation must win over the bare `stopped` status.
  it.each<{
    name: string;
    roster: Parameters<typeof getAgentVisualStatus>[0];
    localOp: Parameters<typeof getAgentVisualStatus>[1];
    label: string;
    orbState: string;
  }>([
    {
      name: "busy updating orb for a server-side rebuilding agent",
      roster: { status: "rebuilding", operation: null },
      localOp: "idle",
      label: "updating...",
      orbState: "busy",
    },
    {
      name: "attention when the agent needs the user to sign in again",
      roster: { status: "not_authenticated", operation: null },
      localOp: "idle",
      label: "needs you to sign in",
      orbState: "attention",
    },
    {
      name: "attention when the agent needs the user to set it up",
      roster: { status: "unprovisioned", operation: null },
      localOp: "idle",
      label: "needs to be set up",
      orbState: "attention",
    },
    {
      name: "a roster operation beats a stopped status",
      roster: { status: "stopped", operation: "backing_up" },
      localOp: "idle",
      label: "backing up...",
      orbState: "busy",
    },
    {
      name: "this tab's own operation beats the roster",
      roster: { status: "alive", operation: null },
      localOp: "stopping",
      label: "stopping...",
      orbState: "busy",
    },
    {
      name: "the stopped label stays distinct from waiting-on-user labels",
      roster: { status: "stopped", operation: null },
      localOp: "idle",
      label: "stopped",
      orbState: "off",
    },
    {
      name: "a local delete shows the deleting orb, not the generic busy one",
      roster: { status: "alive", operation: null },
      localOp: "deleting",
      label: "deleting...",
      orbState: "deleting",
    },
  ])("$name", ({ roster, localOp, label, orbState }) => {
    const result = getAgentVisualStatus(roster, localOp, "", "idle");
    expect(result.label).toBe(label);
    expect(result.orbState).toBe(orbState);
  });

  it("a failure message replaces the label but keeps the orb state", () => {
    const result = getAgentVisualStatus(
      { status: "alive", operation: null },
      "idle",
      "docker down",
      "idle",
    );
    expect(result.label).toBe("docker down");
    expect(result.orbState).toBe(
      getAgentVisualStatus(
        { status: "alive", operation: null },
        "idle",
        "",
        "idle",
      ).orbState,
    );
  });
});
