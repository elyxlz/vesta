import { describe, expect, it } from "vitest";
import { linkify } from "./linkify";

describe("linkify", () => {
  it.each<[string, string, string]>([
    [
      "returns plain text with HTML escaping",
      "hello <world>",
      "hello &lt;world&gt;",
    ],
    ["renders bold markdown", "**bold**", "<strong>bold</strong>"],
    ["renders italic markdown", "*italic*", "<em>italic</em>"],
    ["renders inline code", "`code`", "<code>code</code>"],
    ["escapes ampersands in text", "a & b", "a &amp; b"],
    ["handles empty string", "", ""],
    [
      "converts a URL to an anchor carrying target and rel",
      "visit https://example.com today",
      'visit <a href="https://example.com" target="_blank" rel="noopener">https://example.com</a> today',
    ],
    [
      "escapes ampersands in both the href and the display text",
      "https://example.com?a=1&b=2",
      '<a href="https://example.com?a=1&amp;b=2" target="_blank" rel="noopener">https://example.com?a=1&amp;b=2</a>',
    ],
    [
      "escapes HTML in the surrounding text around a link",
      '<script> https://example.com "test"',
      '&lt;script&gt; <a href="https://example.com" target="_blank" rel="noopener">https://example.com</a> &quot;test&quot;',
    ],
  ])("%s", (_name, input, expected) => {
    expect(linkify(input)).toBe(expected);
  });
});
