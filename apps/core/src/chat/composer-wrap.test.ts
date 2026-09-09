import { describe, expect, it } from "vitest";
import { composerExpandedNext } from "./composer-wrap";

describe("composer row expansion", () => {
  it("stays collapsed while the text is empty or fits with room to spare", () => {
    expect(composerExpandedNext(false, "", 300, 0)).toBe(false);
    expect(composerExpandedNext(true, "   ", 300, 10)).toBe(false);
    expect(composerExpandedNext(false, "hello", 300, 200)).toBe(false);
  });

  it("expands a hair before the last word would wrap", () => {
    expect(composerExpandedNext(false, "hello", 300, 292)).toBe(false);
    expect(composerExpandedNext(false, "hello", 300, 293)).toBe(true);
  });

  it("holds the expanded row until the text clearly fits again", () => {
    expect(composerExpandedNext(true, "hello", 300, 280)).toBe(true);
    expect(composerExpandedNext(true, "hello", 300, 276)).toBe(false);
  });

  it("always expands on a newline", () => {
    expect(composerExpandedNext(false, "a\nb", 300, 20)).toBe(true);
  });

  it("keeps its previous answer until the collapsed width is known", () => {
    expect(composerExpandedNext(true, "hello", 0, 500)).toBe(true);
    expect(composerExpandedNext(false, "hello", 0, 500)).toBe(false);
  });
});
