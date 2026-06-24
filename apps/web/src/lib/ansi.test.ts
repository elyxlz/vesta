import { describe, expect, it } from "vitest";
import { stripAnsi } from "./ansi";

describe("stripAnsi", () => {
  it.each<[string, string, string]>([
    ["returns plain text unchanged", "hello world", "hello world"],
    ["strips SGR color codes", "\x1b[31mred\x1b[0m", "red"],
    [
      "strips bold and combined codes",
      "\x1b[1;32mbold green\x1b[0m",
      "bold green",
    ],
    ["strips OSC sequences (title sets)", "\x1b]0;title\x07text", "text"],
    ["strips charset switching sequences", "\x1b(Btext", "text"],
    [
      "handles multiple codes in one string",
      "\x1b[1mA\x1b[0m \x1b[34mB\x1b[0m",
      "A B",
    ],
    [
      "strips OSC sequences with ST terminator",
      "\x1b]0;title\x1b\\text",
      "text",
    ],
    [
      "strips colon-delimited truecolor codes",
      "\x1b[38:5:196mred\x1b[0m",
      "red",
    ],
    ["returns empty string for escape-only input", "\x1b[31m\x1b[0m", ""],
    ["returns empty string for empty input", "", ""],
  ])("%s", (_name, input, expected) => {
    expect(stripAnsi(input)).toBe(expected);
  });
});
