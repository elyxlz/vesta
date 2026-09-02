import { describe, it, expect } from "vitest";
import type { ChatMessage } from "@vesta/core";
import { buildDecorated, lastSeenIndex } from "./rows";

function userMsg(ts: string): ChatMessage {
  return { type: "user", text: "hi", ts };
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
      { type: "assistant", text: "hey", ts: "2026-06-08T10:02:00" },
      userMsg("2026-06-08T10:03:00"),
    ]);
    expect(rows.map((r) => r.isGroupEnd)).toEqual([false, true, true, true]);
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
