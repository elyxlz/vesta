import { describe, expect, it } from "vitest";
import { messageSegments } from "./message-links";

describe("messageSegments", () => {
  it("returns one plain segment for text without URLs", () => {
    expect(messageSegments("hello there")).toEqual([
      { text: "hello there", url: null },
    ]);
  });

  it("splits a URL into a tappable segment between plain ones", () => {
    expect(messageSegments("see https://vesta.run for more")).toEqual([
      { text: "see ", url: null },
      { text: "https://vesta.run", url: "https://vesta.run" },
      { text: " for more", url: null },
    ]);
  });

  it("keeps trailing sentence punctuation out of the URL", () => {
    expect(messageSegments("check https://vesta.run/docs.")).toEqual([
      { text: "check ", url: null },
      { text: "https://vesta.run/docs", url: "https://vesta.run/docs" },
      { text: ".", url: null },
    ]);
  });

  it("handles multiple URLs and preserves query strings", () => {
    expect(
      messageSegments("https://a.example/x?q=1 and http://b.example"),
    ).toEqual([
      { text: "https://a.example/x?q=1", url: "https://a.example/x?q=1" },
      { text: " and ", url: null },
      { text: "http://b.example", url: "http://b.example" },
    ]);
  });

  it("returns no segments for empty text", () => {
    expect(messageSegments("")).toEqual([]);
  });
});
