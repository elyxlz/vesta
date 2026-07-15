import { describe, expect, it } from "vitest";
import { getAgentPageKeys } from "./pager-model";

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
});
