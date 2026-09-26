import { describe, expect, it } from "vitest";
import { pageSwitchFor } from "./page-switch";

describe("pageSwitchFor", () => {
  it.each([
    [
      "a touch window leaves switching to the bottom bar",
      { bottomNav: true, narrow: true, onDashboard: false, onChat: true },
      null,
    ],
    [
      "a narrow mouse window on the dashboard offers chat",
      { bottomNav: false, narrow: true, onDashboard: true, onChat: false },
      "chat",
    ],
    [
      "a narrow mouse window on chat offers the dashboard",
      { bottomNav: false, narrow: true, onDashboard: false, onChat: true },
      "dashboard",
    ],
    [
      "a wide window on chat offers the dashboard",
      { bottomNav: false, narrow: false, onDashboard: false, onChat: true },
      "dashboard",
    ],
    [
      "a wide window on the dashboard offers nothing",
      { bottomNav: false, narrow: false, onDashboard: true, onChat: false },
      null,
    ],
    [
      "a subpage offers nothing",
      { bottomNav: false, narrow: true, onDashboard: false, onChat: false },
      null,
    ],
  ] as const)("%s", (_, input, expected) => {
    expect(pageSwitchFor(input)).toBe(expected);
  });
});
