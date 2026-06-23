import { describe, it, expect } from "vitest";
import type { VestaEvent } from "@/lib/types";
import { buildDecorated, rowKey } from "./virtual";

function userMsg(ts: string): VestaEvent {
  return { type: "user", text: "hi", ts };
}

describe("rowKey", () => {
  it("uses ts and type when ts is present", () => {
    expect(rowKey(userMsg("2026-06-08T10:00:00Z"), 3)).toBe(
      "2026-06-08T10:00:00Z-user",
    );
  });

  it("falls back to a positional key when ts is missing", () => {
    expect(rowKey({ type: "user", text: "hi" }, 3)).toBe("i-3");
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

  it("uses a tight gap between consecutive tool calls", () => {
    const rows = buildDecorated([
      {
        type: "tool_start",
        tool: "Bash",
        input: "ls",
        ts: "2026-06-08T10:00:00Z",
      },
      {
        type: "tool_start",
        tool: "Bash",
        input: "pwd",
        ts: "2026-06-08T10:00:01Z",
      },
    ]);
    expect(rows[1].gap).toBe("mt-1");
  });
});
