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
