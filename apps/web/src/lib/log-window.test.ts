import { describe, it, expect } from "vitest";
import {
  AT_BOTTOM_THRESHOLD_PX,
  BASE_WINDOW_LINES,
  LOAD_OLDER_SCREENS,
  WINDOW_STEP_LINES,
  distanceFromEnd,
  grownWindow,
  isAtBottom,
  shouldGrow,
} from "./log-window";

function metrics(scrollTop: number, scrollHeight = 20000, clientHeight = 600) {
  return { scrollTop, scrollHeight, clientHeight };
}

describe("distanceFromEnd", () => {
  it("measures the gap between the viewport bottom and the content end", () => {
    expect(distanceFromEnd(metrics(19400))).toBe(0);
    expect(distanceFromEnd(metrics(19000))).toBe(400);
  });
});

describe("isAtBottom", () => {
  it("counts a viewport within the threshold of the end as pinned", () => {
    expect(isAtBottom(metrics(19400 - AT_BOTTOM_THRESHOLD_PX))).toBe(true);
    expect(isAtBottom(metrics(19400 - AT_BOTTOM_THRESHOLD_PX - 1))).toBe(false);
  });
});

describe("shouldGrow", () => {
  it("grows when hidden lines remain and the user is within the preload margin", () => {
    const nearTop = metrics(600 * LOAD_OLDER_SCREENS - 1);
    expect(shouldGrow(nearTop, true)).toBe(true);
  });

  it("does not grow past the preload margin", () => {
    const deep = metrics(600 * LOAD_OLDER_SCREENS + 1);
    expect(shouldGrow(deep, true)).toBe(false);
  });

  it("does not grow when the whole buffer is already rendered", () => {
    const nearTop = metrics(0);
    expect(shouldGrow(nearTop, false)).toBe(false);
  });
});

describe("grownWindow", () => {
  it("adds one step", () => {
    expect(grownWindow(BASE_WINDOW_LINES, 5000)).toBe(
      BASE_WINDOW_LINES + WINDOW_STEP_LINES,
    );
  });

  it("never renders more lines than the buffer holds", () => {
    expect(grownWindow(4900, 5000)).toBe(5000);
    expect(grownWindow(5000, 5000)).toBe(5000);
  });
});
