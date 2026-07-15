import { describe, expect, it } from "vitest";
import type { VestaEvent } from "../api/types";
import { createInvertedChatRows } from "./chat-list-model";

const events: VestaEvent[] = [
  { type: "user", text: "first", ts: "2026-07-15T10:00:00Z" },
  { type: "chat", text: "second", ts: "2026-07-15T10:00:01Z" },
  { type: "chat", text: "latest", ts: "2026-07-15T10:00:02Z" },
];

describe("inverted chat rows", () => {
  it("puts the latest message at the native list origin", () => {
    const rows = createInvertedChatRows(events, false, false);

    expect(
      rows.map((row) => (row.kind === "event" ? row.event.type : row.kind)),
    ).toEqual(["chat", "chat", "user"]);
    expect(rows[0]?.key).toBe("2026-07-15T10:00:02Z-chat");
  });

  it("appends older pages without moving the existing latest rows", () => {
    const initialRows = createInvertedChatRows(events, false, false);
    const paginatedRows = createInvertedChatRows(
      [
        { type: "chat", text: "older", ts: "2026-07-15T09:59:59Z" },
        ...events,
      ],
      false,
      false,
    );

    expect(
      paginatedRows.slice(0, initialRows.length).map((row) => row.key),
    ).toEqual(initialRows.map((row) => row.key));
    expect(paginatedRows.at(-1)?.key).toBe("2026-07-15T09:59:59Z-chat");
  });

  it("places typing at the latest edge and joins consecutive agent bubbles", () => {
    const rows = createInvertedChatRows(events, false, true);

    expect(rows[0]).toMatchObject({
      kind: "typing",
      startsNewBubbleGroup: false,
    });
    expect(rows[1]).toMatchObject({
      kind: "event",
      endsBubbleGroup: false,
    });
  });
});
