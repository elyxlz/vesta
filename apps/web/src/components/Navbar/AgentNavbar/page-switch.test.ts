import { describe, expect, it } from "vitest";
import { pageSwitchFor } from "./page-switch";

const DASHBOARD = { onDashboard: true, onChat: false };
const CHAT = { onDashboard: false, onChat: true };
const SUBPAGE = { onDashboard: false, onChat: false };

describe("pageSwitchFor", () => {
  it.each([
    [
      "a touch window leaves switching to the bottom bar",
      "touch-narrow",
      CHAT,
      null,
    ],
    [
      "a narrow mouse window on the dashboard offers chat",
      "mouse-narrow",
      DASHBOARD,
      "chat",
    ],
    [
      "a narrow mouse window on chat offers the dashboard",
      "mouse-narrow",
      CHAT,
      "dashboard",
    ],
    ["a wide window on chat offers the dashboard", "wide", CHAT, "dashboard"],
    ["a wide window on the dashboard offers nothing", "wide", DASHBOARD, null],
    ["a subpage offers nothing", "mouse-narrow", SUBPAGE, null],
  ] as const)("%s", (_, layout, page, expected) => {
    expect(pageSwitchFor(layout, page)).toBe(expected);
  });
});
