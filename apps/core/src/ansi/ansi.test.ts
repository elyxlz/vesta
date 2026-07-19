import { describe, expect, it } from "vitest"

import { parseAnsi, resolveAnsiColor, stripAnsi } from "./ansi"

describe("parseAnsi", () => {
  it("preserves basic colors and resets them", () => {
    expect(parseAnsi("plain \x1b[31mred\x1b[0m plain")).toEqual([
      { text: "plain ", style: {} },
      { text: "red", style: { foreground: { kind: "palette", index: 1 } } },
      { text: " plain", style: {} },
    ])
  })

  it("supports bright, 256-color, and true-color output", () => {
    expect(parseAnsi("\x1b[94mblue\x1b[38;5;196mred\x1b[38;2;1;2;3mrgb")).toEqual([
      { text: "blue", style: { foreground: { kind: "palette", index: 12 } } },
      { text: "red", style: { foreground: { kind: "palette", index: 196 } } },
      { text: "rgb", style: { foreground: { kind: "rgb", value: "rgb(1, 2, 3)" } } },
    ])
  })

  it("carries the terminal attributes and clears them individually", () => {
    expect(parseAnsi("\x1b[1;3;4mattrs\x1b[24mno-underline\x1b[22mno-bold")).toEqual([
      { text: "attrs", style: { bold: true, italic: true, underline: true } },
      { text: "no-underline", style: { bold: true, italic: true } },
      { text: "no-bold", style: { italic: true } },
    ])
  })

  it("sets a background color and clears it", () => {
    expect(parseAnsi("\x1b[41mbg\x1b[49mplain")).toEqual([
      { text: "bg", style: { background: { kind: "palette", index: 1 } } },
      { text: "plain", style: {} },
    ])
  })

  it("removes non-style terminal controls", () => {
    expect(parseAnsi("one\x1b[2Ktwo\x1b]0;title\x07three")).toEqual([
      { text: "one", style: {} },
      { text: "two", style: {} },
      { text: "three", style: {} },
    ])
  })
})

describe("resolveAnsiColor", () => {
  const palette = Array.from({ length: 16 }, (_unused, index) => `p${String(index)}`)

  it("maps standard and bright indices through the base palette", () => {
    expect(resolveAnsiColor({ kind: "palette", index: 1 }, palette)).toBe("p1")
    expect(resolveAnsiColor({ kind: "palette", index: 12 }, palette)).toBe("p12")
  })

  it("passes truecolor through unchanged", () => {
    expect(resolveAnsiColor({ kind: "rgb", value: "rgb(1, 2, 3)" }, palette)).toBe("rgb(1, 2, 3)")
  })

  it("maps the xterm color cube", () => {
    expect(resolveAnsiColor({ kind: "palette", index: 196 }, palette)).toBe("rgb(255, 0, 0)")
  })

  it("maps the grayscale ramp", () => {
    expect(resolveAnsiColor({ kind: "palette", index: 232 }, palette)).toBe("rgb(8, 8, 8)")
    expect(resolveAnsiColor({ kind: "palette", index: 255 }, palette)).toBe("rgb(238, 238, 238)")
  })
})

describe("stripAnsi", () => {
  it.each<[string, string, string]>([
    ["returns plain text unchanged", "hello world", "hello world"],
    ["strips SGR color codes", "\x1b[31mred\x1b[0m", "red"],
    ["strips bold and combined codes", "\x1b[1;32mbold green\x1b[0m", "bold green"],
    ["strips OSC sequences (title sets)", "\x1b]0;title\x07text", "text"],
    ["strips charset switching sequences", "\x1b(Btext", "text"],
    ["handles multiple codes in one string", "\x1b[1mA\x1b[0m \x1b[34mB\x1b[0m", "A B"],
    ["strips OSC sequences with ST terminator", "\x1b]0;title\x1b\\text", "text"],
    ["strips colon-delimited truecolor codes", "\x1b[38:5:196mred\x1b[0m", "red"],
    ["returns empty string for escape-only input", "\x1b[31m\x1b[0m", ""],
    ["returns empty string for empty input", "", ""],
  ])("%s", (_name, input, expected) => {
    expect(stripAnsi(input)).toBe(expected)
  })
})
