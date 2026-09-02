import { describe, expect, it } from "vitest";

import { appChatFixtures as fixtures } from "../../fixtures/app-chat-events";
import type { ChatMessage, HistoryPage } from "../chat/chat-stream-model";
import { parseChatEvent, parseHistoryPage } from "./parse-chat";

// The generated fixture is `as const`, so its arrays are readonly tuples; the compile-time
// check compares against the readonly view of the canonical types.
type DeepReadonly<T> = T extends (infer U)[]
  ? readonly DeepReadonly<U>[]
  : T extends object
    ? { readonly [K in keyof T]: DeepReadonly<T[K]> }
    : T;

// The fixtures are produced by the app-chat service's real intake and store paths
// (agent/skills/app-chat/cli/tests/test_chat_events_fixture.py, REGEN_EVENT_FIXTURES=1). Parsing
// them with the boundary parser proves the service->client seam at runtime, and the `satisfies`
// checks prove it at compile time: a renamed field on either side fails `npm run check`.
describe("app-chat event contract (service fixtures)", () => {
  it("types the echo frame and the history page at compile time", () => {
    const echo = fixtures.echo satisfies DeepReadonly<ChatMessage>;
    const page = fixtures.history satisfies DeepReadonly<HistoryPage>;
    expect(echo.intent_id).toBe("intent-1");
    expect(page.cursor).toBeNull();
  });

  it("parses the live echo of a send, carrying the client's intent id and the store id", () => {
    const parsed = parseChatEvent(JSON.parse(JSON.stringify(fixtures.echo)));
    expect(parsed).toEqual({
      type: "user",
      id: 1,
      ts: "2026-01-01T00:00:00+00:00",
      text: "here is the photo",
      input_method: "typed",
      intent_id: "intent-1",
    });
  });

  it("parses every event on the history page, attachments included", () => {
    const page = parseHistoryPage(JSON.parse(JSON.stringify(fixtures.history)));
    expect(page.cursor).toBeNull();
    expect(page.events.map((event) => event.type)).toEqual(["user", "chat"]);
    const reply = page.events[1];
    expect(reply?.type === "chat" ? reply.attachments : null).toEqual([
      {
        id: "att-photo",
        name: "photo.jpg",
        mime: "image/jpeg",
        size: 12345,
        width: 640,
        height: 480,
      },
    ]);
  });

  it("drops an event the parser cannot classify instead of rendering it", () => {
    expect(parseChatEvent({ type: "chat", id: 3 })).toBeNull();
    expect(parseChatEvent({ type: "mystery", id: 3, text: "x" })).toBeNull();
    expect(
      parseHistoryPage({ events: [{ type: "user", id: "1", text: "x" }] })
        .events,
    ).toEqual([]);
  });
});
