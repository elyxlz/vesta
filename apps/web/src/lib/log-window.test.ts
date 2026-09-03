import { describe, it, expect } from "vitest";
import { LOAD_OLDER_SCREENS, grownWindow, shouldGrow } from "./log-window";

function metrics(scrollTop: number, scrollHeight = 20000, clientHeight = 600) {
  return { scrollTop, scrollHeight, clientHeight };
}

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
  it("never renders more lines than the buffer holds", () => {
    expect(grownWindow(4900, 5000)).toBe(5000);
    expect(grownWindow(5000, 5000)).toBe(5000);
  });
});
