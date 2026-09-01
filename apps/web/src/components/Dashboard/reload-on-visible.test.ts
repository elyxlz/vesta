import { describe, expect, it } from "vitest";
import { shouldReloadDashboard } from "./reload-on-visible";

describe("shouldReloadDashboard", () => {
  it("does not reload while the window is hidden", () => {
    expect(
      shouldReloadDashboard({
        visible: false,
        hasDashboard: true,
        loadedRev: 1,
        currentRev: 2,
      }),
    ).toBe(false);
  });

  it("does not reload when there is no dashboard", () => {
    expect(
      shouldReloadDashboard({
        visible: true,
        hasDashboard: false,
        loadedRev: null,
        currentRev: 0,
      }),
    ).toBe(false);
  });

  it("does not reload when the loaded frame is already current", () => {
    expect(
      shouldReloadDashboard({
        visible: true,
        hasDashboard: true,
        loadedRev: 3,
        currentRev: 3,
      }),
    ).toBe(false);
  });

  it("reloads when the loaded frame is behind the current rev", () => {
    expect(
      shouldReloadDashboard({
        visible: true,
        hasDashboard: true,
        loadedRev: 2,
        currentRev: 5,
      }),
    ).toBe(true);
  });

  it("reloads when nothing ever finished loading", () => {
    expect(
      shouldReloadDashboard({
        visible: true,
        hasDashboard: true,
        loadedRev: null,
        currentRev: 1,
      }),
    ).toBe(true);
  });
});
