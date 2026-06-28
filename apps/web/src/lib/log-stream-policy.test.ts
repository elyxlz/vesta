import { describe, it, expect } from "vitest";
import { logStreamAction } from "./log-stream-policy";

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
