import { describe, it, expect } from "vitest";
import {
  AT_BOTTOM_THRESHOLD_PX,
  IDLE_LATCH,
  distanceFromEnd,
  onResizeTick,
  onRowsChange,
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
  it.each<{
    name: string;
    metrics: { scrollTop: number; scrollHeight: number; clientHeight: number };
    canLoad: boolean;
    expected: Partial<{
      atBottom: boolean;
      loadOlder: boolean;
      nearTop: boolean;
    }>;
  }>([
    {
      name: "reports pinned within the bottom threshold",
      metrics: metrics(1400 - AT_BOTTOM_THRESHOLD_PX),
      canLoad: true,
      expected: { atBottom: true, loadOlder: false },
    },
    {
      name: "reports unpinned deep in the list without loading",
      metrics: metrics(5000, 10000),
      canLoad: true,
      expected: { atBottom: false, loadOlder: false, nearTop: false },
    },
    {
      name: "preloads older history while the user still has scroll runway",
      metrics: metrics(1700, 10000),
      canLoad: true,
      expected: { loadOlder: true, nearTop: false },
    },
    {
      name: "flags the user as waiting at the top of loaded history",
      metrics: metrics(40, 10000),
      canLoad: true,
      expected: { loadOlder: true, nearTop: true },
    },
    {
      name: "does not load older history when the caller cannot load",
      metrics: metrics(40),
      canLoad: false,
      expected: { loadOlder: false },
    },
    {
      // Content barely taller than the viewport: at-bottom and near-top at once.
      name: "does not load older history while pinned in a short conversation",
      metrics: metrics(50, 700, 600),
      canLoad: true,
      expected: { atBottom: true, loadOlder: false },
    },
  ])("$name", ({ metrics: m, canLoad, expected }) => {
    const tick = onScrollTick(m, IDLE_LATCH, canLoad);
    for (const [key, value] of Object.entries(expected)) {
      expect(tick[key as keyof typeof expected]).toBe(value);
    }
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

describe("onResizeTick", () => {
  it("re-pins a pinned viewport when content grows beneath it", () => {
    const tick = onResizeTick(metrics(1000), IDLE_LATCH, true);
    expect(tick.scrollToEnd).toBe("instant");
    expect(tick.atBottom).toBe(null);
  });

  it("recomputes the pinned flag for an unpinned viewport", () => {
    const tick = onResizeTick(metrics(1000), IDLE_LATCH, false);
    expect(tick.scrollToEnd).toBe(null);
    expect(tick.atBottom).toBe(false);
  });

  it("re-aims a mid-flight follow whose target moved, so it cannot land short", () => {
    const latch = startFollow(metrics(1000, 2000));
    const tick = onResizeTick(metrics(1200, 2600), latch, true);
    expect(tick.scrollToEnd).toBe("smooth");
    expect(tick.latch.following).toBe(true);
    expect(tick.latch.lastDistance).toBe(distanceFromEnd(metrics(1200, 2600)));
    expect(tick.atBottom).toBe(null);
  });

  it("lands a follow that the resize left within the bottom threshold", () => {
    const latch = startFollow(metrics(1000));
    const tick = onResizeTick(
      metrics(1400 - AT_BOTTOM_THRESHOLD_PX),
      latch,
      true,
    );
    expect(tick.latch.following).toBe(false);
    expect(tick.scrollToEnd).toBe(null);
    expect(tick.atBottom).toBe(true);
  });
});

describe("onRowsChange", () => {
  it("restores the viewport over older rows landing above it, even while pinned", () => {
    expect(onRowsChange("k5", "k1", 10, 30, false)).toBe("restore");
    expect(onRowsChange("k5", "k1", 10, 30, true)).toBe("restore");
  });

  it("jumps the first page of history onto the latest message", () => {
    expect(onRowsChange(null, "k1", 0, 20, true)).toBe("jump");
  });

  it("follows an append only while pinned", () => {
    expect(onRowsChange("k1", "k1", 10, 11, true)).toBe("follow");
    expect(onRowsChange("k1", "k1", 10, 11, false)).toBe("none");
  });

  it("leaves in-place edits that keep the count alone", () => {
    expect(onRowsChange("k1", "k1", 10, 10, true)).toBe("none");
  });
});

describe("restoredScrollTop", () => {
  it("replays the height the prepend added above the viewport", () => {
    expect(restoredScrollTop({ scrollTop: 40, scrollHeight: 2000 }, 3200)).toBe(
      1240,
    );
  });
});
