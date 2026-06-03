import { describe, it } from "vitest";
import fc from "fast-check";
import { stripAnsi } from "./ansi";

// Generator that concatenates escape-sequence fragments, partial sequences, and plain
// text, producing both valid and adversarially nested/broken ANSI input.
const ansiText = fc.string({
  unit: fc.constantFrom(
    "\x1b[31m",
    "\x1b[0m",
    "\x1b[1;32m",
    "\x1b[38:5:196m",
    "\x1b]0;title\x07",
    "\x1b]0;title\x1b\\",
    "\x1b(B",
    "\x1b",
    "[",
    "]",
    "(",
    "m",
    ";",
    "0",
    "1",
    "\x07",
    "\\",
    "a",
    " ",
    "text",
  ),
  maxLength: 30,
});

describe("stripAnsi properties", () => {
  it("is idempotent: stripping twice equals stripping once", () => {
    fc.assert(
      fc.property(ansiText, (text) => {
        const once = stripAnsi(text);
        return stripAnsi(once) === once;
      }),
    );
  });

  it("output never contains a strippable escape sequence", () => {
    fc.assert(
      fc.property(ansiText, (text) => {
        const out = stripAnsi(text);
        // Anything ESC + [ / ] / ( would have been matched by another pass.
        // eslint-disable-next-line no-control-regex
        return !/\x1b(?:\[[0-9;:]*[a-zA-Z]|\].*?(?:\x07|\x1b\\)|\([A-Z0-9])/.test(
          out,
        );
      }),
    );
  });

  it("leaves escape-free text unchanged", () => {
    fc.assert(
      fc.property(
        fc
          .string({ unit: "grapheme", maxLength: 200 })
          .filter((s) => !s.includes("\x1b")),
        (text) => stripAnsi(text) === text,
      ),
    );
  });
});
