import { describe, expect, it } from "vitest";
import { getAgentPageKeys } from "./pager-model";

describe("agent pager", () => {
  it("lists the enabled pages in order", () => {
    expect(
      getAgentPageKeys({
        showDashboardPage: true,
        showNotificationsPage: false,
        showLogsPage: false,
      }),
    ).toEqual(["chat", "dashboard"]);
    expect(
      getAgentPageKeys({
        showDashboardPage: false,
        showNotificationsPage: true,
        showLogsPage: true,
      }),
    ).toEqual(["chat", "notifications", "logs"]);
  });

  it("shows chat alone when every optional page is off", () => {
    expect(
      getAgentPageKeys({
        showDashboardPage: false,
        showNotificationsPage: false,
        showLogsPage: false,
      }),
    ).toEqual(["chat"]);
  });
});
