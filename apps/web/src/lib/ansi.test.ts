import { describe, expect, it } from "vitest";
import { stripAnsi } from "./ansi";

describe("stripAnsi", () => {
  it("returns plain text unchanged", () => {
    expect(stripAnsi("hello world")).toBe("hello world");
  });

  it("strips SGR color codes", () => {
    expect(stripAnsi("\x1b[31mred\x1b[0m")).toBe("red");
  });

  it("strips bold and combined codes", () => {
    expect(stripAnsi("\x1b[1;32mbold green\x1b[0m")).toBe("bold green");
  });

  it("strips OSC sequences (title sets)", () => {
    expect(stripAnsi("\x1b]0;title\x07text")).toBe("text");
  });

  it("strips charset switching sequences", () => {
    expect(stripAnsi("\x1b(Btext")).toBe("text");
  });

  it("handles multiple codes in one string", () => {
    expect(stripAnsi("\x1b[1mA\x1b[0m \x1b[34mB\x1b[0m")).toBe("A B");
  });

  it("strips OSC sequences with ST terminator", () => {
    expect(stripAnsi("\x1b]0;title\x1b\\text")).toBe("text");
  });

  it("strips colon-delimited truecolor codes", () => {
    expect(stripAnsi("\x1b[38:5:196mred\x1b[0m")).toBe("red");
  });

  it("returns empty string for escape-only input", () => {
    expect(stripAnsi("\x1b[31m\x1b[0m")).toBe("");
  });

  it("returns empty string for empty input", () => {
    expect(stripAnsi("")).toBe("");
  });
});
