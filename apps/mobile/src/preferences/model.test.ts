import { describe, expect, it } from "vitest";
import {
  getNaturalChatPacingForAgent,
  getShowToolCallsForAgent,
  initialPreferences,
  readStoredPreferences,
} from "./model";

describe("preference persistence", () => {
  it("uses first-run defaults only when no preferences exist", () => {
    expect(readStoredPreferences(null)).toEqual(initialPreferences);
    expect(initialPreferences.remoteNotifications).toBe(true);
    expect(initialPreferences.naturalChatPacingDefault).toBe(true);
    expect(initialPreferences.naturalChatPacingByAgent).toEqual({});
    expect(initialPreferences.showToolCallsDefault).toBe(false);
    expect(initialPreferences.showToolCallsByAgent).toEqual({});
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
    const migrated = readStoredPreferences(
      '{"theme":"unknown","showToolCalls":true}',
    );
    expect(migrated).toMatchObject({
      theme: "system",
      showToolCallsDefault: true,
      showToolCallsByAgent: {},
      notificationPreviews: false,
    });
    expect(getShowToolCallsForAgent(migrated, "Ada")).toBe(true);
    expect(readStoredPreferences("not json")).toEqual(initialPreferences);
  });

  it("restores tool-call visibility independently for each agent", () => {
    const preferences = readStoredPreferences(
      JSON.stringify({
        showToolCallsDefault: false,
        showToolCallsByAgent: {
          Ada: true,
          Ben: false,
          malformed: "yes",
        },
      }),
    );

    expect(preferences.showToolCallsByAgent).toEqual({
      Ada: true,
      Ben: false,
    });
    expect(getShowToolCallsForAgent(preferences, "Ada")).toBe(true);
    expect(getShowToolCallsForAgent(preferences, "Ben")).toBe(false);
    expect(getShowToolCallsForAgent(preferences, "New agent")).toBe(false);
  });

  it("lets an agent override the migrated global preference", () => {
    const preferences = {
      ...initialPreferences,
      showToolCallsDefault: true,
      showToolCallsByAgent: { Ada: false },
    };

    expect(getShowToolCallsForAgent(preferences, "Ada")).toBe(false);
    expect(getShowToolCallsForAgent(preferences, "Ben")).toBe(true);
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
