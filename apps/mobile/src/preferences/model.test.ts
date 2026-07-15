import { describe, expect, it } from "vitest";
import { initialPreferences, readStoredPreferences } from "./model";

describe("preference persistence", () => {
  it("uses first-run defaults only when no preferences exist", () => {
    expect(readStoredPreferences(null)).toEqual(initialPreferences);
    expect(initialPreferences.remoteNotifications).toBe(true);
    expect(initialPreferences.showToolCalls).toBe(false);
    expect(initialPreferences.showNotificationsPage).toBe(false);
    expect(initialPreferences.showLogsPage).toBe(false);
  });

  it("restores optional agent pages", () => {
    expect(
      readStoredPreferences(
        JSON.stringify({
          showNotificationsPage: true,
          showLogsPage: true,
        }),
      ),
    ).toMatchObject({
      showNotificationsPage: true,
      showLogsPage: true,
    });
  });

  it("restores disabled notifications instead of replacing them with defaults", () => {
    expect(
      readStoredPreferences(
        JSON.stringify({
          remoteNotifications: false,
          pushChatReplies: false,
          pushStatusChanges: false,
        }),
      ),
    ).toMatchObject({
      remoteNotifications: false,
      pushChatReplies: false,
      pushStatusChanges: false,
    });
  });

  it("falls back field-by-field for malformed or older state", () => {
    expect(
      readStoredPreferences('{"theme":"unknown","showToolCalls":true}'),
    ).toMatchObject({
      theme: "system",
      showToolCalls: true,
      notificationPreviews: false,
    });
    expect(readStoredPreferences("not json")).toEqual(initialPreferences);
  });
});
