import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ASTNode } from "react-native-markdown-display";
import {
  chatDateLabel,
  isFinalMarkdownNode,
  isSameCalendarDay,
  resolveMarkdownLink,
} from "./chat-message-model";

function markdownNode(
  key: string,
  type: string,
  children: ASTNode[] = [],
): ASTNode {
  return {
    type,
    sourceType: type,
    key,
    content: "",
    markup: "",
    tokenIndex: 0,
    index: 0,
    attributes: {},
    children,
  };
}

describe("isSameCalendarDay", () => {
  it.each([
    {
      case: "different times on one day",
      left: new Date(2026, 6, 15, 0, 5),
      right: new Date(2026, 6, 15, 23, 55),
      expected: true,
    },
    {
      case: "the same day number in different months",
      left: new Date(2026, 6, 15),
      right: new Date(2026, 7, 15),
      expected: false,
    },
    {
      case: "adjacent days across a month boundary",
      left: new Date(2026, 6, 31, 23, 59),
      right: new Date(2026, 7, 1, 0, 1),
      expected: false,
    },
    {
      case: "the same date in different years",
      left: new Date(2025, 6, 15),
      right: new Date(2026, 6, 15),
      expected: false,
    },
  ])("answers $expected for $case", ({ left, right, expected }) => {
    expect(isSameCalendarDay(left, right)).toBe(expected);
  });
});

describe("chatDateLabel", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 7, 17, 12, 0));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("labels a message from the current day Today", () => {
    expect(chatDateLabel("2026-08-17T08:30:00")).toBe("Today");
  });

  it("labels the previous day Yesterday", () => {
    expect(chatDateLabel("2026-08-16T23:00:00")).toBe("Yesterday");
  });

  it("labels yesterday across a month boundary", () => {
    vi.setSystemTime(new Date(2026, 8, 1, 9, 0));
    expect(chatDateLabel("2026-08-31T22:00:00")).toBe("Yesterday");
  });

  it("spells out an older same-year day without the year", () => {
    const label = chatDateLabel("2026-08-12T10:00:00");
    expect(label).toContain("Wednesday");
    expect(label).toContain("August");
    expect(label).toContain("12");
    expect(label).not.toContain("2026");
  });

  it("adds the year to a date from another year", () => {
    const label = chatDateLabel("2025-12-26T10:00:00");
    expect(label).toContain("Friday");
    expect(label).toContain("December");
    expect(label).toContain("26");
    expect(label).toContain("2025");
  });

  it.each([
    { case: "a missing timestamp", timestamp: null },
    { case: "an unparseable timestamp", timestamp: "not-a-timestamp" },
  ])("labels $case Earlier", ({ timestamp }) => {
    expect(chatDateLabel(timestamp)).toBe("Earlier");
  });
});

describe("resolveMarkdownLink", () => {
  it.each([
    {
      case: "an https url",
      href: "https://example.com/page",
      url: "https://example.com/page",
      opener: "in-app-browser",
    },
    {
      case: "an http url",
      href: "http://example.com",
      url: "http://example.com",
      opener: "in-app-browser",
    },
    {
      case: "an uppercase scheme",
      href: "HTTPS://EXAMPLE.COM",
      url: "HTTPS://EXAMPLE.COM",
      opener: "in-app-browser",
    },
    {
      case: "a bare domain with whitespace",
      href: "  example.com/path  ",
      url: "https://example.com/path",
      opener: "in-app-browser",
    },
    {
      case: "a schemeless path with leading slashes",
      href: "//example.com",
      url: "https://example.com",
      opener: "in-app-browser",
    },
    {
      case: "a mailto link",
      href: "mailto:vesta@example.com",
      url: "mailto:vesta@example.com",
      opener: "system",
    },
    {
      case: "a tel link",
      href: "tel:+15551234567",
      url: "tel:+15551234567",
      opener: "system",
    },
    {
      case: "an sms link",
      href: "sms:+15551234567",
      url: "sms:+15551234567",
      opener: "system",
    },
    {
      case: "an unsupported scheme",
      href: "ftp://example.com/file",
      url: "ftp://example.com/file",
      opener: "unsupported",
    },
  ])("resolves $case", ({ href, url, opener }) => {
    expect(resolveMarkdownLink(href)).toEqual({ url, opener });
  });
});

describe("isFinalMarkdownNode", () => {
  it("marks the last leaf of the last block under the body", () => {
    const text = markdownNode("text", "textgroup");
    const paragraph = markdownNode("paragraph", "paragraph", [text]);
    const body = markdownNode("body", "body", [paragraph]);

    expect(isFinalMarkdownNode(text, [paragraph, body])).toBe(true);
  });

  it("rejects a node that is not the last child of its parent", () => {
    const first = markdownNode("first", "textgroup");
    const last = markdownNode("last", "textgroup");
    const paragraph = markdownNode("paragraph", "paragraph", [first, last]);
    const body = markdownNode("body", "body", [paragraph]);

    expect(isFinalMarkdownNode(first, [paragraph, body])).toBe(false);
  });

  it("rejects a last leaf whose own block is not the last block", () => {
    const text = markdownNode("text", "textgroup");
    const firstParagraph = markdownNode("first", "paragraph", [text]);
    const lastParagraph = markdownNode("last", "paragraph");
    const body = markdownNode("body", "body", [firstParagraph, lastParagraph]);

    expect(isFinalMarkdownNode(text, [firstParagraph, body])).toBe(false);
  });

  it("rejects a chain that ends inside a blockquote instead of the body", () => {
    const text = markdownNode("text", "textgroup");
    const paragraph = markdownNode("paragraph", "paragraph", [text]);
    const blockquote = markdownNode("quote", "blockquote", [paragraph]);

    expect(isFinalMarkdownNode(text, [paragraph, blockquote])).toBe(false);
  });

  it("rejects a node with no parents", () => {
    expect(isFinalMarkdownNode(markdownNode("text", "textgroup"), [])).toBe(
      false,
    );
  });
});
