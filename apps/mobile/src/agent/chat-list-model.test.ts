import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../chat/chat-stream-model";
import { createInvertedChatRows } from "./chat-list-model";

const events: ChatMessage[] = [
  { type: "user", text: "first", ts: "2026-07-15T10:00:00Z" },
  { type: "chat", text: "second", ts: "2026-07-15T10:00:01Z" },
  { type: "chat", text: "latest", ts: "2026-07-15T10:00:02Z" },
];

describe("inverted chat rows", () => {
  it("puts the latest message at the native list origin", () => {
    const rows = createInvertedChatRows(events, false, false);

    expect(
      rows.map((row) => (row.kind === "event" ? row.event.type : row.kind)),
    ).toEqual(["chat", "chat", "user", "date"]);
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

    expect(paginatedRows.slice(0, events.length).map((row) => row.key)).toEqual(
      initialRows.slice(0, events.length).map((row) => row.key),
    );
    expect(paginatedRows.at(-2)?.key).toBe("2026-07-15T09:59:59Z-chat");
    expect(paginatedRows.at(-1)?.key).toBe("date-2026-07-15");
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

  it("starts agent spacing on the first tool after a user", () => {
    const rows = createInvertedChatRows(
      [
        { type: "user", text: "do this", ts: "2026-07-15T10:00:00Z" },
        {
          type: "tool_start",
          tool: "Read",
          input: "first.txt",
          ts: "2026-07-15T10:00:01Z",
        },
        {
          type: "tool_start",
          tool: "Read",
          input: "second.txt",
          ts: "2026-07-15T10:00:02Z",
        },
        { type: "chat", text: "done", ts: "2026-07-15T10:00:03Z" },
      ],
      true,
      false,
    );

    expect(
      [...rows].reverse().flatMap((row) =>
        row.kind === "event"
          ? [
              {
                type: row.event.type,
                startsNewBubbleGroup: row.startsNewBubbleGroup,
              },
            ]
          : [],
      ),
    ).toEqual([
      { type: "user", startsNewBubbleGroup: false },
      { type: "tool_start", startsNewBubbleGroup: true },
      { type: "tool_start", startsNewBubbleGroup: false },
      { type: "chat", startsNewBubbleGroup: false },
    ]);
  });

  it("starts a new same-sender bubble group after five minutes", () => {
    const rows = createInvertedChatRows(
      [
        { type: "chat", text: "first", ts: "2026-07-15T10:00:00Z" },
        { type: "chat", text: "nearby", ts: "2026-07-15T10:04:59Z" },
        { type: "chat", text: "later", ts: "2026-07-15T10:09:59Z" },
      ],
      false,
      false,
    );

    expect(
      [...rows].reverse().flatMap((row) =>
        row.kind === "event"
          ? [
              {
                text: row.event.type === "chat" ? row.event.text : "",
                startsNewBubbleGroup: row.startsNewBubbleGroup,
                endsBubbleGroup: row.endsBubbleGroup,
              },
            ]
          : [],
      ),
    ).toEqual([
      {
        text: "first",
        startsNewBubbleGroup: false,
        endsBubbleGroup: false,
      },
      {
        text: "nearby",
        startsNewBubbleGroup: false,
        endsBubbleGroup: true,
      },
      {
        text: "later",
        startsNewBubbleGroup: true,
        endsBubbleGroup: true,
      },
    ]);
  });

  it("keeps same-sender bubbles grouped without usable timestamps", () => {
    const rows = createInvertedChatRows(
      [
        { type: "user", text: "first" },
        { type: "user", text: "second", ts: "not-a-date" },
      ],
      false,
      false,
    );

    expect(
      rows
        .filter((row) => row.kind === "event")
        .map((row) => row.startsNewBubbleGroup),
    ).toEqual([false, false]);
  });

  it("keeps typing grouped with a visible tool", () => {
    const rows = createInvertedChatRows(
      [
        { type: "user", text: "do this", ts: "2026-07-15T10:00:00Z" },
        {
          type: "tool_start",
          tool: "Read",
          input: "file.txt",
          ts: "2026-07-15T10:00:01Z",
        },
      ],
      true,
      true,
    );

    expect(rows[0]).toMatchObject({
      kind: "typing",
      startsNewBubbleGroup: false,
    });
    expect(rows[1]).toMatchObject({
      kind: "event",
      startsNewBubbleGroup: true,
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
