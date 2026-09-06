import { describe, expect, it } from "vitest";
import { conversationPhase, splitSpokenTail } from "./conversation-panel";

describe("conversation phase", () => {
  const live = {
    listening: true,
    micMuted: false,
    speaking: false,
    thinking: false,
  };

  it("reads connecting until the session listens, whatever else is true", () => {
    expect(
      conversationPhase({ ...live, listening: false, speaking: true }),
    ).toBe("connecting");
  });

  it("ranks the agent talking above a muted mic, and mute above thinking", () => {
    expect(conversationPhase({ ...live, speaking: true, micMuted: true })).toBe(
      "speaking",
    );
    expect(conversationPhase({ ...live, micMuted: true, thinking: true })).toBe(
      "muted",
    );
    expect(conversationPhase({ ...live, thinking: true })).toBe("thinking");
    expect(conversationPhase(live)).toBe("listening");
  });
});

describe("spoken tail", () => {
  it("splits the last word off for emphasis", () => {
    expect(splitSpokenTail("book the room")).toEqual({
      head: "book the ",
      tail: "room",
    });
  });

  it("treats a single word as the tail", () => {
    expect(splitSpokenTail("hello")).toEqual({ head: "", tail: "hello" });
    expect(splitSpokenTail("")).toEqual({ head: "", tail: "" });
  });
});
