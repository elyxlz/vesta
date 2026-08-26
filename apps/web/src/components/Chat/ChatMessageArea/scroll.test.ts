import { describe, it, expect } from "vitest";
import {
  AT_BOTTOM_THRESHOLD_PX,
  IDLE_LATCH,
  distanceFromEnd,
  isPrepend,
  onScrollTick,
  restoredScrollTop,
  startFollow,
} from "./scroll";

function metrics(scrollTop: number, scrollHeight = 2000, clientHeight = 600) {
  return { scrollTop, scrollHeight, clientHeight };
}

describe("distanceFromEnd", () => {
  it("measures the gap between the viewport bottom and the content end", () => {
    expect(distanceFromEnd(metrics(1400))).toBe(0);
    expect(distanceFromEnd(metrics(1000))).toBe(400);
  });
});

describe("onScrollTick while idle", () => {
  it("reports pinned within the bottom threshold", () => {
    const tick = onScrollTick(
      metrics(1400 - AT_BOTTOM_THRESHOLD_PX),
      IDLE_LATCH,
      true,
    );
    expect(tick.atBottom).toBe(true);
    expect(tick.loadOlder).toBe(false);
  });

  it("reports unpinned deep in the list without loading", () => {
    const tick = onScrollTick(metrics(5000, 10000), IDLE_LATCH, true);
    expect(tick.atBottom).toBe(false);
    expect(tick.loadOlder).toBe(false);
    expect(tick.nearTop).toBe(false);
  });

  it("preloads older history while the user still has scroll runway", () => {
    const tick = onScrollTick(metrics(1700, 10000), IDLE_LATCH, true);
    expect(tick.loadOlder).toBe(true);
    expect(tick.nearTop).toBe(false);
  });

  it("flags the user as waiting at the top of loaded history", () => {
    const tick = onScrollTick(metrics(40, 10000), IDLE_LATCH, true);
    expect(tick.loadOlder).toBe(true);
    expect(tick.nearTop).toBe(true);
  });

  it("does not load older history when the caller cannot load", () => {
    const tick = onScrollTick(metrics(40), IDLE_LATCH, false);
    expect(tick.loadOlder).toBe(false);
  });

  it("does not load older history while pinned in a short conversation", () => {
    // Content barely taller than the viewport: at-bottom and near-top at once.
    const tick = onScrollTick(metrics(50, 700, 600), IDLE_LATCH, true);
    expect(tick.atBottom).toBe(true);
    expect(tick.loadOlder).toBe(false);
  });
});

describe("onScrollTick while following a smooth scroll to the latest message", () => {
  it("holds the pinned state while the distance shrinks", () => {
    const latch = startFollow(metrics(1000));
    const tick = onScrollTick(metrics(1100), latch, true);
    expect(tick.atBottom).toBe(null);
    expect(tick.latch.following).toBe(true);
    expect(tick.loadOlder).toBe(false);
  });

  it("lands and reports pinned when the distance reaches the threshold", () => {
    const latch = startFollow(metrics(1000));
    const tick = onScrollTick(
      metrics(1400 - AT_BOTTOM_THRESHOLD_PX),
      latch,
      true,
    );
    expect(tick.atBottom).toBe(true);
    expect(tick.latch.following).toBe(false);
  });

  it("hands control back when the user scrolls away mid-follow", () => {
    const latch = startFollow(metrics(1000));
    const afterProgress = onScrollTick(metrics(1100), latch, true);
    const tick = onScrollTick(metrics(900), afterProgress.latch, true);
    expect(tick.atBottom).toBe(false);
    expect(tick.latch.following).toBe(false);
  });
});

describe("isPrepend", () => {
  it("detects older rows landing above the existing first row", () => {
    expect(isPrepend("k5", "k1", 10, 30)).toBe(true);
  });

  it("ignores the first page of history", () => {
    expect(isPrepend(null, "k1", 0, 20)).toBe(false);
  });

  it("ignores appends, which keep the first row", () => {
    expect(isPrepend("k1", "k1", 10, 11)).toBe(false);
  });

  it("ignores in-place edits that keep the count", () => {
    expect(isPrepend("k1", "k1", 10, 10)).toBe(false);
  });
});

describe("restoredScrollTop", () => {
  it("replays the height the prepend added above the viewport", () => {
    expect(restoredScrollTop({ scrollTop: 40, scrollHeight: 2000 }, 3200)).toBe(
      1240,
    );
  });
});
