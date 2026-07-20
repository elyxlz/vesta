import { describe, expect, it } from "vitest";
import type { ChatMessage } from "@vesta/core";
import { createInvertedChatRows } from "./chat-list-model";

const events: ChatMessage[] = [
  { type: "user", text: "first", ts: "2026-07-15T10:00:00Z" },
  { type: "chat", text: "second", ts: "2026-07-15T10:00:01Z" },
  { type: "chat", text: "latest", ts: "2026-07-15T10:00:02Z" },
];

describe("inverted chat rows", () => {
  it("puts the latest message at the native list origin", () => {
    const rows = createInvertedChatRows(events, false);

    expect(
      rows.map((row) => (row.kind === "event" ? row.event.type : row.kind)),
    ).toEqual(["chat", "chat", "user", "date"]);
    expect(rows[0]?.key).toBe("2026-07-15T10:00:02Z-chat");
  });

  it("appends older pages without moving the existing latest rows", () => {
    const initialRows = createInvertedChatRows(events, false);
    const paginatedRows = createInvertedChatRows(
      [
        { type: "chat", text: "older", ts: "2026-07-15T09:59:59Z" },
        ...events,
      ],
      false,
    );

    expect(paginatedRows.slice(0, events.length).map((row) => row.key)).toEqual(
      initialRows.slice(0, events.length).map((row) => row.key),
    );
    expect(paginatedRows.at(-2)?.key).toBe("2026-07-15T09:59:59Z-chat");
    expect(paginatedRows.at(-1)?.key).toBe("date-2026-07-15");
  });

  it("places typing at the latest edge and joins consecutive agent bubbles", () => {
    const rows = createInvertedChatRows(events, true);

    expect(rows[0]).toMatchObject({
      kind: "typing",
      startsNewBubbleGroup: false,
    });
    expect(rows[1]).toMatchObject({
      kind: "event",
      endsBubbleGroup: false,
    });
  });

  it("inserts a header above each local calendar day", () => {
    const rows = createInvertedChatRows(
      [
        { type: "user", text: "day one", ts: "2026-07-14T10:00:00" },
        { type: "chat", text: "day one reply", ts: "2026-07-14T10:01:00" },
        { type: "chat", text: "day two", ts: "2026-07-15T10:00:00" },
      ],
      false,
    );

    expect(rows.map((row) => row.key)).toEqual([
      "2026-07-15T10:00:00-chat",
      "date-2026-07-15",
      "2026-07-14T10:01:00-chat",
      "2026-07-14T10:00:00-user",
      "date-2026-07-14",
    ]);
    expect(rows[0]).toMatchObject({
      startsNewBubbleGroup: false,
      endsBubbleGroup: true,
    });
    expect(rows[2]).toMatchObject({ startsNewBubbleGroup: true });
  });
});
