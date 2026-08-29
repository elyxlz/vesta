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
    expect(initialPreferences.naturalChatPacingByAgent).toEqual({});
    expect(initialPreferences.showNotificationsPage).toBe(false);
    expect(initialPreferences.showLogsPage).toBe(false);
    expect(initialPreferences.shareLocation).toBe(true);
  });

  it("restores the location switch and defaults it on", () => {
    expect(
      readStoredPreferences(JSON.stringify({ shareLocation: false })),
    ).toMatchObject({
      shareLocation: false,
    });
    expect(
      readStoredPreferences(JSON.stringify({ theme: "dark" })),
    ).toMatchObject({
      shareLocation: true,
    });
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
        }),
      ),
    ).toMatchObject({
      remoteNotifications: false,
      pushChatReplies: false,
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
});
