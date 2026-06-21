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
  ])("%s", (_name, input, expected) => {
    expect(linkify(input)).toBe(expected);
  });

  it("converts URLs to anchor tags", () => {
    const result = linkify("visit https://example.com today");
    expect(result).toContain('<a href="https://example.com"');
    expect(result).toContain("https://example.com</a>");
    expect(result).toContain('target="_blank"');
  });

  it("handles multiple URLs", () => {
    const result = linkify("a https://a.com b http://b.com c");
    expect(result).toContain("https://a.com</a>");
    expect(result).toContain("http://b.com</a>");
  });

  it("escapes HTML in surrounding text and URL href", () => {
    const result = linkify('<script> https://example.com "test"');
    expect(result).toContain("&lt;script&gt;");
    expect(result).toContain("&quot;test&quot;");
    expect(result).toContain("https://example.com");
    expect(result).toContain('target="_blank"');
  });

  it("escapes ampersands in both URL href and display text", () => {
    const result = linkify("https://example.com?a=1&b=2");
    expect(result).toContain('href="https://example.com?a=1&amp;b=2"');
    expect(result).toContain("&amp;b=2</a>");
  });

  it("includes rel=noopener on links", () => {
    const result = linkify("https://example.com");
    expect(result).toContain('rel="noopener"');
  });
});
