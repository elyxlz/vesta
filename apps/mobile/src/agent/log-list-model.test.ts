import { describe, expect, it } from "vitest";
import { addLatestLogLine, type LogLine } from "./log-list-model";

describe("inverted log lines", () => {
  it("puts each new line at the native list origin", () => {
    const first = addLatestLogLine([], { id: 0, text: "first" });
    const second = addLatestLogLine(first, { id: 1, text: "latest" });

    expect(second).toEqual([
      { id: 1, text: "latest" },
      { id: 0, text: "first" },
    ]);
  });

  it("keeps the latest 5000 lines", () => {
    const existing: LogLine[] = Array.from({ length: 5000 }, (_, index) => {
      const id = 4999 - index;
      return { id, text: String(id) };
    });

    const result = addLatestLogLine(existing, { id: 5000, text: "latest" });

    expect(result).toHaveLength(5000);
    expect(result[0]?.id).toBe(5000);
    expect(result.at(-1)?.id).toBe(1);
  });
});
