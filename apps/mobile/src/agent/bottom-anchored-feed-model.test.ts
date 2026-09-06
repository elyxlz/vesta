import { describe, expect, it } from "vitest";
import {
  FEED_BOTTOM_THRESHOLD,
  distanceFromSettledBottom,
} from "./bottom-anchored-feed-model";

describe("distanceFromSettledBottom", () => {
  it("reads zero for a reader resting at the end of the content", () => {
    expect(
      distanceFromSettledBottom({
        settledContentHeight: 1000,
        contentHeight: 1000,
        viewportHeight: 600,
        offset: 400,
      }),
    ).toBe(0);
  });

  it("keeps a reader at the bottom near it while a burst of lines lands", () => {
    // Five 18pt lines arrived and the position hold reported the grown height before the
    // follow decision; against the settled height the reader is still at the end.
    expect(
      distanceFromSettledBottom({
        settledContentHeight: 1000,
        contentHeight: 1090,
        viewportHeight: 600,
        offset: 400,
      }),
    ).toBeLessThanOrEqual(FEED_BOTTOM_THRESHOLD);
  });

  it("reads far for a reader who scrolled up into history", () => {
    expect(
      distanceFromSettledBottom({
        settledContentHeight: 1000,
        contentHeight: 1000,
        viewportHeight: 600,
        offset: 100,
      }),
    ).toBeGreaterThan(FEED_BOTTOM_THRESHOLD);
  });
});
