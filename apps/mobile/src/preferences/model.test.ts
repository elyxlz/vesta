import { describe, expect, it } from "vitest";
import {
  getNaturalChatPacingForAgent,
  initialPreferences,
  readStoredPreferences,
} from "./model";

describe("preference persistence", () => {
  it("uses first-run defaults only when no preferences exist", () => {
    expect(readStoredPreferences(null)).toEqual(initialPreferences);
    expect(initialPreferences.remoteNotifications).toBe(true);
    expect(initialPreferences.naturalChatPacingDefault).toBe(true);
    expect(initialPreferences.naturalChatPacingByAgent).toEqual({});
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
    const migrated = readStoredPreferences('{"theme":"unknown"}');
    expect(migrated).toMatchObject({
      theme: "system",
      notificationPreviews: false,
    });
    expect(readStoredPreferences("not json")).toEqual(initialPreferences);
  });

  it("restores natural chat pacing independently for each agent", () => {
    const preferences = readStoredPreferences(
      JSON.stringify({
        naturalChatPacingDefault: true,
        naturalChatPacingByAgent: {
          Ada: false,
          Ben: true,
          malformed: "no",
        },
      }),
    );

    expect(preferences.naturalChatPacingByAgent).toEqual({
      Ada: false,
      Ben: true,
    });
    expect(getNaturalChatPacingForAgent(preferences, "Ada")).toBe(false);
    expect(getNaturalChatPacingForAgent(preferences, "Ben")).toBe(true);
    expect(getNaturalChatPacingForAgent(preferences, "New agent")).toBe(true);
  });

  it("migrates the global natural chat pacing preference", () => {
    const preferences = readStoredPreferences(
      JSON.stringify({ naturalChatPacing: false }),
    );

    expect(preferences.naturalChatPacingDefault).toBe(false);
    expect(getNaturalChatPacingForAgent(preferences, "Ada")).toBe(false);
  });
});
