import { describe, expect, it } from "vitest";
import {
  CODE_TOKEN_COLORS,
  HIGHLIGHT_MAX_CHARS,
  highlightCode,
  type CodeTokenKind,
} from "./code-highlight";

function kindsOf(code: string, info: string, text: string): CodeTokenKind[] {
  return highlightCode(code, info)
    .lines.flat()
    .filter((token) => token.text === text)
    .map((token) => token.kind);
}

describe("highlightCode language resolution", () => {
  it.each([
    ["sh", "bash"],
    ["zsh", "bash"],
    ["py", "python"],
    ["Python", "python"],
    ['python title="x.py"', "python"],
    ["tsx", "typescript"],
    ["yml", "yaml"],
    ["html", "xml"],
    ["ini", "toml"],
  ])("resolves %s to %s", (info, language) => {
    expect(highlightCode("x", info).language).toBe(language);
  });

  it.each([null, "", "   ", "brainfuck"])(
    "treats %j as no language and returns only plain tokens",
    (info) => {
      const result = highlightCode("if x then y", info);
      expect(result.language).toBeNull();
      expect(result.lines).toEqual([[{ text: "if x then y", kind: "plain" }]]);
    },
  );
});

describe("highlightCode token kinds", () => {
  it.each([
    ["python", "def f():\n    return 'hi'", "def", "keyword"],
    ["python", "def f():\n    return 'hi'", "'hi'", "string"],
    ["python", "x = 42", "42", "number"],
    ["python", "# note", "# note", "comment"],
    ["bash", 'echo "hi"', '"hi"', "string"],
    ["typescript", "const n: number = 1", "const", "keyword"],
    ["typescript", "function greet() {}", "greet", "function"],
    ["rust", "fn main() {}", "fn", "keyword"],
    ["go", "func main() {}", "func", "keyword"],
    ["json", '{"a": 1}', "1", "number"],
    ["sql", "SELECT 1", "SELECT", "keyword"],
  ] as const)("in %s, %j marks %j as %s", (info, code, text, kind) => {
    expect(kindsOf(code, info, text)).toContain(kind);
  });
});

describe("highlightCode lines", () => {
  it("splits a multi-line string into one string token per line", () => {
    const result = highlightCode('x = """a\nb"""', "python");
    expect(result.lines).toHaveLength(2);
    expect(result.lines.flat().some((token) => token.text.includes("\n"))).toBe(
      false,
    );
    expect(result.lines[1]).toEqual([{ text: 'b"""', kind: "string" }]);
  });

  it("keeps an empty line as an empty array", () => {
    expect(highlightCode("a\n\nb", null).lines).toEqual([
      [{ text: "a", kind: "plain" }],
      [],
      [{ text: "b", kind: "plain" }],
    ]);
  });

  it("returns one empty line for empty code", () => {
    expect(highlightCode("", "python").lines).toEqual([[]]);
  });

  it("returns plain tokens above the size cap but keeps the language", () => {
    const code = "x".repeat(HIGHLIGHT_MAX_CHARS + 1);
    expect(highlightCode(code, "python")).toEqual({
      language: "python",
      lines: [[{ text: code, kind: "plain" }]],
    });
  });
});

describe("CODE_TOKEN_COLORS", () => {
  it("maps every kind to its design token", () => {
    expect(CODE_TOKEN_COLORS).toEqual({
      plain: "foreground",
      keyword: "ansi-magenta",
      string: "ansi-green",
      number: "ansi-yellow",
      comment: "tertiary-foreground",
      function: "ansi-blue",
      type: "ansi-cyan",
      variable: "ansi-red",
      operator: "muted-foreground",
    });
  });
});
