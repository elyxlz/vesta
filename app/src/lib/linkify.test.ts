import { describe, expect, it } from "vitest";
import { linkify } from "./linkify";

describe("linkify", () => {
  it("returns plain text with HTML escaping", () => {
    expect(linkify("hello <world>")).toBe("hello &lt;world&gt;");
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

  it("escapes HTML in surrounding text but preserves URL", () => {
    const result = linkify('<script> https://example.com "test"');
    expect(result).toContain("&lt;script&gt;");
    expect(result).toContain("&quot;test&quot;");
    expect(result).toContain('href="https://example.com"');
  });

  it("renders bold markdown", () => {
    expect(linkify("**bold**")).toBe("<strong>bold</strong>");
  });

  it("renders italic markdown", () => {
    expect(linkify("*italic*")).toBe("<em>italic</em>");
  });

  it("renders inline code", () => {
    expect(linkify("`code`")).toBe("<code>code</code>");
  });

  it("escapes ampersands in text", () => {
    expect(linkify("a & b")).toBe("a &amp; b");
  });

  it("escapes ampersands in URL display text but preserves href", () => {
    const result = linkify("https://example.com?a=1&b=2");
    expect(result).toContain('href="https://example.com?a=1&b=2"');
    expect(result).toContain("&amp;b=2</a>");
  });

  it("includes rel=noopener on links", () => {
    const result = linkify("https://example.com");
    expect(result).toContain('rel="noopener"');
  });

  it("handles empty string", () => {
    expect(linkify("")).toBe("");
  });
});
