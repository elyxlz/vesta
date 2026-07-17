import { describe, it } from "vitest";
import fc from "fast-check";
import { linkify } from "./linkify";

// Generator mixing URLs, markdown markers, HTML-dangerous chars, placeholder-injection
// attempts, and plain text.
const linkifyText = fc.string({
  unit: fc.constantFrom(
    "http://a.b/c",
    "https://x.y/z?q=1&r=2",
    "**",
    "*",
    "`",
    "\x00",
    "\x00URL0\x00",
    "URL",
    "<script>",
    "</script>",
    "<",
    ">",
    "&",
    '"',
    "'",
    "word",
    " ",
    "\n",
    "0",
  ),
  maxLength: 20,
});

const TAG_RE = /<\/?(?:a|code|strong|em)(?:\s[^>]*)?>/g;

const NUL = "\x00";
const MARKER_RE = new RegExp(`[*\`${NUL}]`);

describe("linkify properties", () => {
  it("never throws on any input", () => {
    fc.assert(
      fc.property(linkifyText, (text) => {
        linkify(text);
        return true;
      }),
    );
    fc.assert(
      fc.property(fc.string({ unit: "binary", maxLength: 200 }), (text) => {
        linkify(text);
        return true;
      }),
    );
  });

  it("output never contains a raw < outside the tags linkify itself generates (XSS safety)", () => {
    fc.assert(
      fc.property(linkifyText, (text) => {
        const withoutGeneratedTags = linkify(text).replace(TAG_RE, "");
        return !withoutGeneratedTags.includes("<");
      }),
    );
  });

  it("equals plain HTML escaping when there are no URLs, markdown markers, or placeholders", () => {
    const plainText = fc
      .string({ unit: "grapheme", maxLength: 200 })
      .filter((s) => !/https?:\/\//.test(s) && !MARKER_RE.test(s));
    fc.assert(
      fc.property(plainText, (text) => {
        const expected = text
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;");
        return linkify(text) === expected;
      }),
    );
  });
});
