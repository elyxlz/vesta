import { describe, expect, it } from "vitest";

import { parseChatEvent } from "./parse-chat";

// The room-addressed fields the chat node stamps on every stored message. They are optional on the
// wire, so a frame without them parses exactly as it did before rooms existed.
describe("parseChatEvent room addressing", () => {
  it("keeps the room and the sender on a user event", () => {
    expect(
      parseChatEvent({
        type: "user",
        id: 1,
        ts: "2026-09-04T09:00:00.000Z",
        room: "dm:scout",
        sender: "user",
        text: "are we still on for friday?",
        input_method: "typed",
        intent_id: "c-sample-1",
      }),
    ).toEqual({
      type: "user",
      id: 1,
      ts: "2026-09-04T09:00:00.000Z",
      room: "dm:scout",
      sender: "user",
      text: "are we still on for friday?",
      input_method: "typed",
      intent_id: "c-sample-1",
    });
  });

  it("keeps the room and the sender on a chat event", () => {
    expect(
      parseChatEvent({
        type: "chat",
        id: 2,
        room: "grp-0011223344556677",
        sender: "scout",
        text: "yes, 19:00",
      }),
    ).toEqual({
      type: "chat",
      id: 2,
      room: "grp-0011223344556677",
      sender: "scout",
      text: "yes, 19:00",
    });
  });

  it("parses a user and a chat event carrying neither field", () => {
    expect(parseChatEvent({ type: "user", id: 3, text: "hi" })).toEqual({
      type: "user",
      id: 3,
      text: "hi",
    });
    expect(parseChatEvent({ type: "chat", id: 4, text: "hello" })).toEqual({
      type: "chat",
      id: 4,
      text: "hello",
    });
  });

  it("drops an event whose room or sender is the wrong type", () => {
    expect(
      parseChatEvent({ type: "user", id: 5, text: "hi", room: 7 }),
    ).toBeNull();
    expect(
      parseChatEvent({ type: "user", id: 5, text: "hi", sender: 7 }),
    ).toBeNull();
    expect(
      parseChatEvent({ type: "chat", id: 6, text: "hi", room: 7 }),
    ).toBeNull();
    expect(
      parseChatEvent({ type: "chat", id: 6, text: "hi", sender: 7 }),
    ).toBeNull();
  });
});

// The chat node stores only user and chat messages, so a frame naming any other kind is a shape no
// producer emits. It drops at the boundary instead of reaching the view as a row nothing renders.
describe("parseChatEvent on a kind the node never emits", () => {
  it.each([
    { type: "tool_start", id: 10, tool: "Bash", input: "ls" },
    { type: "tool_end", id: 11, tool: "Bash" },
    { type: "error", id: 12, text: "boom" },
    { type: "rate_limited", id: 13, text: "wait", window: "5h", resets_at: 1 },
    { type: "notification", id: 14, source: "chat", summary: "hi" },
    { type: "notification_cleared", id: 15, notif_id: "n-1" },
    { type: "subagent_start", id: 16, agent_id: "a-1", agent_type: "explore" },
    { type: "subagent_stop", id: 17, agent_id: "a-1", agent_type: "explore" },
  ])("drops a $type frame", (frame) => {
    expect(parseChatEvent(frame)).toBeNull();
  });
});
