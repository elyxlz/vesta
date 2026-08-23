import { describe, expect, it } from "vitest";
import { getAgentPageKeys } from "./pager-model";

describe("agent pager", () => {
  it("lists the enabled pages in order", () => {
    expect(
      getAgentPageKeys({
        showChatPage: true,
        showDashboardPage: true,
        showNotificationsPage: false,
        showLogsPage: false,
      }),
    ).toEqual(["chat", "dashboard"]);
    expect(
      getAgentPageKeys({
        showChatPage: true,
        showDashboardPage: false,
        showNotificationsPage: true,
        showLogsPage: true,
      }),
    ).toEqual(["chat", "notifications", "logs"]);
  });

  it("keeps chat when every page is off", () => {
    expect(
      getAgentPageKeys({
        showChatPage: false,
        showDashboardPage: false,
        showNotificationsPage: false,
        showLogsPage: false,
      }),
    ).toEqual(["chat"]);
  });
});
