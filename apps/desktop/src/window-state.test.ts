import { describe, expect, it } from "vitest";
import { isOnScreen, parseWindowState } from "./window-state";

const PRIMARY = { x: 0, y: 0, width: 1920, height: 1080 };
const RIGHT = { x: 1920, y: 0, width: 2560, height: 1440 };

describe("parseWindowState", () => {
  it("accepts saved bounds and the maximized flag", () => {
    const state = {
      bounds: { x: 10, y: 20, width: 1300, height: 800 },
      maximized: true,
    };
    expect(parseWindowState(state)).toEqual(state);
  });

  it.each<[string, unknown]>([
    ["nothing saved", null],
    ["no bounds", { maximized: false }],
    [
      "a non-numeric size",
      { bounds: { x: 0, y: 0, width: "1300", height: 800 }, maximized: false },
    ],
    ["a missing flag", { bounds: { x: 0, y: 0, width: 1300, height: 800 } }],
  ])("rejects %s", (_, value) => {
    expect(parseWindowState(value)).toBeNull();
  });
});

describe("isOnScreen", () => {
  it("keeps a window on the second display while it is connected", () => {
    const bounds = { x: 2200, y: 100, width: 1200, height: 750 };
    expect(isOnScreen(bounds, [PRIMARY, RIGHT])).toBe(true);
    expect(isOnScreen(bounds, [PRIMARY])).toBe(false);
  });

  it("drops a window that only shows a sliver on any display", () => {
    const bounds = { x: 1880, y: 100, width: 1200, height: 750 };
    expect(isOnScreen(bounds, [PRIMARY])).toBe(false);
  });
});
