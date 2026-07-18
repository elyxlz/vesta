import { describe, expect, it } from "vitest";
import { parseSseBlock } from "./log-stream";

describe("log stream protocol", () => {
  it("parses named events and multiline data", () => {
    expect(parseSseBlock("event: agent_stopped\ndata: first\ndata: second")).toEqual({
      event: "agent_stopped",
      data: "first\nsecond",
    });
  });

  it("uses the message event by default", () => {
    expect(parseSseBlock("data: ready")).toEqual({
      event: "message",
      data: "ready",
    });
  });

  it("ignores empty blocks", () => {
    expect(parseSseBlock(": keepalive")).toBeNull();
  });
});
