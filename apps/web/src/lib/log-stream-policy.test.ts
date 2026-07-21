import { describe, it, expect } from "vitest";
import {
  logStreamAction,
  isAgentContainerUp,
  replayTailLines,
  LOG_SCROLLBACK_LINES,
} from "./log-stream-policy";
import type { AgentStatus } from "@vesta/core";

describe("logStreamAction", () => {
  it("appends a line with its text", () => {
    expect(logStreamAction({ kind: "Line", text: "hello" })).toEqual({
      kind: "append",
      text: "hello",
    });
  });

  it("treats agent_stopped (End) as terminal, not a reconnect", () => {
    expect(logStreamAction({ kind: "End" })).toEqual({ kind: "stopped" });
  });

  it("reconnects on a transport Error", () => {
    expect(logStreamAction({ kind: "Error", message: "disconnected" })).toEqual(
      { kind: "reconnect" },
    );
  });
});

describe("isAgentContainerUp", () => {
  const up: AgentStatus[] = [
    "alive",
    "starting",
    "setting_up",
    "not_authenticated",
    "unprovisioned",
    "restarting",
  ];
  const down: AgentStatus[] = ["stopped", "dead", "not_found"];

  it.each(up)("treats %s as up (streams live logs)", (status) => {
    expect(isAgentContainerUp(status)).toBe(true);
  });

  it.each(down)("treats %s as down (no live logs)", (status) => {
    expect(isAgentContainerUp(status)).toBe(false);
  });
});

describe("replayTailLines", () => {
  it("asks a fresh stream to replay the full scrollback the viewer keeps", () => {
    expect(replayTailLines(true)).toBe(LOG_SCROLLBACK_LINES);
  });

  it("asks a reconnect for no replay, so the tail is not re-appended", () => {
    expect(replayTailLines(false)).toBe(0);
  });
});
