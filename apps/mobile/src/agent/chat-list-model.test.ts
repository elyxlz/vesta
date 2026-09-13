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
      [{ type: "chat", text: "older", ts: "2026-07-15T09:59:59Z" }, ...events],
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

  it("starts a new same-sender bubble group after five minutes", () => {
    const rows = createInvertedChatRows(
      [
        { type: "chat", text: "first", ts: "2026-07-15T10:00:00Z" },
        { type: "chat", text: "nearby", ts: "2026-07-15T10:04:59Z" },
        { type: "chat", text: "later", ts: "2026-07-15T10:09:59Z" },
      ],
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
    );

    expect(
      rows
        .filter((row) => row.kind === "event")
        .map((row) => row.startsNewBubbleGroup),
    ).toEqual([false, false]);
    expect(rows.at(-1)).toMatchObject({
      kind: "date",
      timestamp: null,
    });
  });

  it("separates undated legacy messages from a newer dated section", () => {
    const rows = createInvertedChatRows(
      [
        { type: "chat", text: "legacy without embedded timestamp" },
        { type: "chat", text: "new", ts: "2026-07-25T10:00:00Z" },
      ],
      false,
    );

    expect(
      [...rows]
        .reverse()
        .map((row) =>
          row.kind === "date"
            ? (row.timestamp ?? "earlier")
            : row.kind === "event"
              ? row.event.type === "chat"
                ? row.event.text
                : row.event.type
              : row.kind,
        ),
    ).toEqual([
      "earlier",
      "legacy without embedded timestamp",
      "2026-07-25T10:00:00Z",
      "new",
    ]);
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

  // A room with several agents alternates senders on the agent side, so a group breaks on the
  // writer as well as on the side: each agent's run opens and closes its own bubble group.
  it("breaks a bubble group when a second agent speaks in the room", () => {
    const rows = createInvertedChatRows(
      [
        {
          type: "chat",
          text: "one",
          ts: "2026-07-15T10:00:00Z",
          sender: "aria",
        },
        {
          type: "chat",
          text: "two",
          ts: "2026-07-15T10:01:00Z",
          sender: "aria",
        },
        {
          type: "chat",
          text: "three",
          ts: "2026-07-15T10:02:00Z",
          sender: "nova",
        },
        {
          type: "chat",
          text: "four",
          ts: "2026-07-15T10:03:00Z",
          sender: "aria",
        },
      ],
      false,
    );

    expect(
      [...rows].reverse().flatMap((row) =>
        row.kind === "event"
          ? [
              {
                startsNewBubbleGroup: row.startsNewBubbleGroup,
                isGroupStart: row.isGroupStart,
                endsBubbleGroup: row.endsBubbleGroup,
              },
            ]
          : [],
      ),
    ).toEqual([
      {
        startsNewBubbleGroup: false,
        isGroupStart: true,
        endsBubbleGroup: false,
      },
      {
        startsNewBubbleGroup: false,
        isGroupStart: false,
        endsBubbleGroup: true,
      },
      { startsNewBubbleGroup: true, isGroupStart: true, endsBubbleGroup: true },
      { startsNewBubbleGroup: true, isGroupStart: true, endsBubbleGroup: true },
    ]);
  });

  it("keeps one agent's run in a single bubble group", () => {
    const rows = createInvertedChatRows(
      [
        {
          type: "chat",
          text: "one",
          ts: "2026-07-15T10:00:00Z",
          sender: "aria",
        },
        {
          type: "chat",
          text: "two",
          ts: "2026-07-15T10:01:00Z",
          sender: "aria",
        },
        {
          type: "chat",
          text: "three",
          ts: "2026-07-15T10:02:00Z",
          sender: "aria",
        },
      ],
      false,
    );

    expect(
      [...rows]
        .reverse()
        .flatMap((row) => (row.kind === "event" ? [row.isGroupStart] : [])),
    ).toEqual([true, false, false]);
  });

  // The user is one sender however many agents answer, so their own bubbles group as always.
  it("groups the user's own bubbles across a room's agents", () => {
    const rows = createInvertedChatRows(
      [
        {
          type: "user",
          text: "hi",
          ts: "2026-07-15T10:00:00Z",
          sender: "user",
        },
        {
          type: "user",
          text: "again",
          ts: "2026-07-15T10:00:30Z",
          sender: "user",
        },
        {
          type: "chat",
          text: "hey",
          ts: "2026-07-15T10:01:00Z",
          sender: "nova",
        },
      ],
      false,
    );

    expect(
      [...rows]
        .reverse()
        .flatMap((row) =>
          row.kind === "event"
            ? [{ start: row.isGroupStart, end: row.endsBubbleGroup }]
            : [],
        ),
    ).toEqual([
      { start: true, end: false },
      { start: false, end: true },
      { start: true, end: true },
    ]);
  });
});
