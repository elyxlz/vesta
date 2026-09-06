import { describe, it, expect } from "vitest";
import type { ChatMessage } from "@vesta/core";
import { buildDecorated, lastSeenIndex, senderCaption } from "./rows";

function userMsg(ts: string): ChatMessage {
  return { type: "user", text: "hi", ts };
}

function chatMsg(sender: string, ts: string): ChatMessage {
  return { type: "chat", text: "hey", ts, sender };
}

describe("buildDecorated", () => {
  it("shows a day stamp on the first dated message and on day boundaries", () => {
    // Local-time (no Z) so the day boundary is deterministic regardless of TZ.
    const rows = buildDecorated([
      userMsg("2026-06-07T23:00:00"),
      userMsg("2026-06-07T23:30:00"),
      userMsg("2026-06-08T00:30:00"),
    ]);
    expect(rows.map((r) => r.showDayStamp)).toEqual([true, false, true]);
    expect(rows[0]?.dayLabel).not.toBe("");
    expect(rows[1]?.dayLabel).toBe("");
  });

  it("produces unique keys when two events share a timestamp and type", () => {
    const rows = buildDecorated([
      userMsg("2026-06-08T10:00:00Z"),
      userMsg("2026-06-08T10:00:00Z"),
      userMsg("2026-06-08T10:00:00Z"),
    ]);
    const keys = rows.map((r) => r.key);
    expect(new Set(keys).size).toBe(3);
    expect(keys[0]).toBe("2026-06-08T10:00:00Z-user");
  });

  it("splits same-sender bubbles after a five-minute pause", () => {
    const rows = buildDecorated([
      userMsg("2026-06-08T10:00:00"),
      userMsg("2026-06-08T10:05:00"),
    ]);
    expect(rows[1]?.gap).toBe("mt-5");
  });

  it("keeps same-sender bubbles tight within five minutes", () => {
    const rows = buildDecorated([
      userMsg("2026-06-08T10:00:00"),
      userMsg("2026-06-08T10:04:00"),
    ]);
    expect(rows[1]?.gap).toBe("mt-1.5");
  });

  it("keeps same-sender bubbles tight when a timestamp is unparseable", () => {
    const rows = buildDecorated([
      userMsg("2026-06-08T10:00:00"),
      userMsg("not-a-date"),
    ]);
    expect(rows[1]?.gap).toBe("mt-1.5");
  });

  it("marks only the last bubble of each group as the group end", () => {
    const rows = buildDecorated([
      userMsg("2026-06-08T10:00:00"),
      userMsg("2026-06-08T10:01:00"),
      {
        type: "notification",
        source: "whatsapp",
        summary: "2 new",
        ts: "2026-06-08T10:02:00",
      },
      userMsg("2026-06-08T10:03:00"),
    ]);
    expect(rows.map((r) => r.isGroupEnd)).toEqual([false, true, true, true]);
  });

  // A room with several agents alternates senders on one side, so grouping breaks on the name as
  // well as on the side: each agent's run opens and closes its own bubble group.
  it("breaks a group when a second agent speaks in the same room", () => {
    const rows = buildDecorated([
      chatMsg("ada", "2026-06-08T10:00:00"),
      chatMsg("ada", "2026-06-08T10:01:00"),
      chatMsg("nova", "2026-06-08T10:02:00"),
      chatMsg("ada", "2026-06-08T10:03:00"),
    ]);
    expect(rows.map((r) => r.isGroupStart)).toEqual([true, false, true, true]);
    expect(rows.map((r) => r.isGroupEnd)).toEqual([false, true, true, true]);
    expect(rows.map((r) => r.gap)).toEqual(["mt-2", "mt-1.5", "mt-5", "mt-5"]);
  });

  it("keeps one agent's run in a single group", () => {
    const rows = buildDecorated([
      chatMsg("ada", "2026-06-08T10:00:00"),
      chatMsg("ada", "2026-06-08T10:01:00"),
      chatMsg("ada", "2026-06-08T10:02:00"),
    ]);
    expect(rows.map((r) => r.isGroupStart)).toEqual([true, false, false]);
    expect(rows.map((r) => r.isGroupEnd)).toEqual([false, false, true]);
  });
});

describe("lastSeenIndex", () => {
  const rows = (...ts: string[]) => buildDecorated(ts.map(userMsg));

  it("keeps the boundary on the previous last row when a prepend shifts indices", () => {
    const before = rows("2026-06-08T10:00:00Z", "2026-06-08T10:01:00Z");
    const prevLastKey = before[before.length - 1]?.key ?? null;
    const after = rows(
      "2026-06-08T09:00:00Z",
      "2026-06-08T10:00:00Z",
      "2026-06-08T10:01:00Z",
    );
    expect(lastSeenIndex(after, prevLastKey)).toBe(2);
  });

  it("marks appended rows as past the boundary", () => {
    const before = rows("2026-06-08T10:00:00Z");
    const prevLastKey = before[0]?.key ?? null;
    const after = rows("2026-06-08T10:00:00Z", "2026-06-08T10:01:00Z");
    expect(lastSeenIndex(after, prevLastKey)).toBe(0);
  });

  it("disables the boundary before the first page and after a reseed", () => {
    const after = rows("2026-06-08T10:00:00Z");
    expect(lastSeenIndex(after, null)).toBe(-1);
    expect(lastSeenIndex(after, "2026-01-01T00:00:00Z-user")).toBe(-1);
  });
});

describe("senderCaption", () => {
  const caption = (messages: ChatMessage[], showSenders = true) =>
    buildDecorated(messages).map((row) => senderCaption(row, showSenders));

  it("names the agent that opens a bubble group in a room with several members", () => {
    expect(
      caption([
        chatMsg("ada", "2026-06-08T10:00:00Z"),
        chatMsg("ada", "2026-06-08T10:01:00Z"),
        chatMsg("nova", "2026-06-08T10:02:00Z"),
      ]),
    ).toEqual(["ada", null, "nova"]);
  });

  it("names nobody in a one-agent conversation", () => {
    expect(caption([chatMsg("ada", "2026-06-08T10:00:00Z")], false)).toEqual([
      null,
    ]);
  });

  it("never names the user, the one member every room shares", () => {
    expect(caption([userMsg("2026-06-08T10:00:00Z")])).toEqual([null]);
  });

  // A row that is not a reply names nobody; senderOf answers "agent" for it, which would
  // otherwise print a member name no room has.
  it("never captions a row that is not a reply", () => {
    expect(
      caption([
        {
          type: "notification",
          source: "whatsapp",
          summary: "2 new",
          ts: "2026-06-08T10:00:00Z",
        },
      ]),
    ).toEqual([null]);
  });
});
