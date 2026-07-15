import { describe, expect, it } from "vitest";
import { parseAnsi, resolveAnsiColor } from "./ansi";

describe("ANSI log parsing", () => {
  it("preserves basic colors and resets them", () => {
    expect(parseAnsi("plain \u001b[31mred\u001b[0m plain")).toEqual([
      { text: "plain ", style: {} },
      {
        text: "red",
        style: { foreground: { kind: "palette", index: 1 } },
      },
      { text: " plain", style: {} },
    ]);
  });

  it("supports bright, 256-color, and true-color output", () => {
    expect(
      parseAnsi("\u001b[94mblue\u001b[38;5;196mred\u001b[38;2;1;2;3mrgb"),
    ).toEqual([
      {
        text: "blue",
        style: { foreground: { kind: "palette", index: 12 } },
      },
      {
        text: "red",
        style: { foreground: { kind: "palette", index: 196 } },
      },
      {
        text: "rgb",
        style: { foreground: { kind: "rgb", value: "rgb(1, 2, 3)" } },
      },
    ]);
  });

  it("removes non-style terminal controls", () => {
    expect(parseAnsi("one\u001b[2Ktwo\u001b]0;title\u0007three")).toEqual([
      { text: "one", style: {} },
      { text: "two", style: {} },
      { text: "three", style: {} },
    ]);
  });

  it("maps the xterm color cube", () => {
    expect(
      resolveAnsiColor(
        { kind: "palette", index: 196 },
        Array.from({ length: 16 }, () => "unused"),
      ),
    ).toBe("rgb(255, 0, 0)");
  });
});
