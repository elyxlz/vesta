import { describe, expect, it } from "vitest";
import { getAgentPageKeys, getPagerAnimationRanges } from "./pager-model";

describe("agent pager", () => {
  it("keeps chat and dashboard fixed and appends enabled pages", () => {
    expect(
      getAgentPageKeys({
        showNotificationsPage: false,
        showLogsPage: false,
      }),
    ).toEqual(["chat", "dashboard"]);
    expect(
      getAgentPageKeys({
        showNotificationsPage: true,
        showLogsPage: true,
      }),
    ).toEqual(["chat", "dashboard", "notifications", "logs"]);
  });

  it("creates a visibility pulse and early-settling pill for every swipe", () => {
    expect(getPagerAnimationRanges(4)).toEqual({
      input: [0, 0.16, 0.84, 1, 1.16, 1.84, 2, 2.16, 2.84, 3],
      selection: [0, 0, 1, 1, 1, 2, 2, 2, 3, 3],
      visibility: [0, 1, 1, 0, 1, 1, 0, 1, 1, 0],
    });
  });
});
