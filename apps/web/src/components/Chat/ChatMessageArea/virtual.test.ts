import { describe, it, expect } from "vitest";
import type { VestaEvent } from "@/lib/types";
import {
  START_INDEX,
  buildDecorated,
  computeFirstIndexShift,
  rowKey,
} from "./virtual";

function userMsg(ts: string): VestaEvent {
  return { type: "user", text: "hi", ts };
}

describe("computeFirstIndexShift", () => {
  const base = 1000;

  it("decrements by the number of prepended items", () => {
    const prev = ["c", "d"];
    const next = ["a", "b", "c", "d"];
    expect(computeFirstIndexShift(prev, next, base)).toBe(base - 2);
  });

  it("does not change on a pure tail append", () => {
    const prev = ["a", "b"];
    const next = ["a", "b", "c"];
    expect(computeFirstIndexShift(prev, next, base)).toBe(base);
  });

  it("increments by the number of front-dropped items (cap)", () => {
    const prev = ["a", "b", "c", "d"];
    const next = ["c", "d", "e"];
    expect(computeFirstIndexShift(prev, next, base)).toBe(base + 2);
  });

  it("re-baselines on a full reset (no key overlap)", () => {
    const prev = ["a", "b"];
    const next = ["x", "y"];
    expect(computeFirstIndexShift(prev, next, base)).toBe(START_INDEX);
  });

  it("applies only the head delta when prepend and tail append happen together", () => {
    const prev = ["c", "d"];
    const next = ["a", "b", "c", "d", "e"];
    expect(computeFirstIndexShift(prev, next, base)).toBe(base - 2);
  });

  it("leaves the index unchanged on empty prev or next", () => {
    expect(computeFirstIndexShift([], ["a"], base)).toBe(base);
    expect(computeFirstIndexShift(["a"], [], base)).toBe(base);
  });
});

describe("rowKey", () => {
  it("uses ts and type when ts is present", () => {
    expect(rowKey(userMsg("2026-06-08T10:00:00Z"), 3)).toBe(
      "2026-06-08T10:00:00Z-user",
    );
  });

  it("falls back to a positional key when ts is missing", () => {
    expect(rowKey({ type: "user", text: "hi" }, 3)).toBe("i-3");
  });

  it("a missing-ts tail item does not disturb the head diff", () => {
    const prev = [rowKey(userMsg("t1"), 0)];
    const next = [
      rowKey(userMsg("t1"), 0),
      rowKey({ type: "user", text: "echo" }, 1),
    ];
    expect(computeFirstIndexShift(prev, next, 1000)).toBe(1000);
  });
});

describe("buildDecorated", () => {
  it("shows a day stamp on the first dated message and on day boundaries", () => {
    // Local-time (no Z) so the day boundary is deterministic regardless of TZ.
    const rows = buildDecorated([
      userMsg("2026-06-07T23:00:00"),
      userMsg("2026-06-07T23:30:00"),
      userMsg("2026-06-08T00:30:00"),
    ]);
    expect(rows.map((r) => r.showDayStamp)).toEqual([true, false, true]);
    expect(rows[0].dayLabel).not.toBe("");
    expect(rows[1].dayLabel).toBe("");
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

  it("groups tool calls onto the preceding message's row", () => {
    const rows = buildDecorated([
      userMsg("2026-06-08T10:00:00Z"),
      {
        type: "tool_start",
        tool: "Bash",
        input: "ls",
        ts: "2026-06-08T10:00:01Z",
      },
      {
        type: "tool_start",
        tool: "Bash",
        input: "pwd",
        ts: "2026-06-08T10:00:02Z",
      },
      { type: "chat", text: "done", ts: "2026-06-08T10:00:03Z" },
    ]);
    expect(rows).toHaveLength(2); // one row per conversation message
    expect(rows[0].event.type).toBe("user");
    expect(
      rows[0].tools.map((t) => (t.type === "tool_start" ? t.input : "")),
    ).toEqual(["ls", "pwd"]);
    expect(rows[1].event.type).toBe("chat");
    expect(rows[1].tools).toEqual([]);
  });

  it("keeps the same row set with or without tool calls (toggle invariant)", () => {
    // The show-tools toggle must not change the virtual list's items — only row heights —
    // or Virtuoso loses its scroll anchor. Same conversation, with/without interleaved tools.
    const withTools = buildDecorated([
      userMsg("2026-06-08T10:00:00Z"),
      {
        type: "tool_start",
        tool: "Bash",
        input: "ls",
        ts: "2026-06-08T10:00:01Z",
      },
      { type: "chat", text: "done", ts: "2026-06-08T10:00:02Z" },
    ]);
    const withoutTools = buildDecorated([
      userMsg("2026-06-08T10:00:00Z"),
      { type: "chat", text: "done", ts: "2026-06-08T10:00:02Z" },
    ]);
    expect(withTools.map((r) => r.key)).toEqual(withoutTools.map((r) => r.key));
  });
});
