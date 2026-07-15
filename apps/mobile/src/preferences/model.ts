export type ThemePreference = "system" | "light" | "dark";

export interface PreferencesState {
  theme: ThemePreference;
  naturalChatPacing: boolean;
  showToolCalls: boolean;
  remoteNotifications: boolean;
  pushChatReplies: boolean;
  pushStatusChanges: boolean;
  notificationPreviews: boolean;
}

export const initialPreferences: PreferencesState = {
  theme: "system",
  naturalChatPacing: true,
  showToolCalls: false,
  remoteNotifications: true,
  pushChatReplies: true,
  pushStatusChanges: true,
  notificationPreviews: false,
};

function isThemePreference(value: unknown): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

export function readStoredPreferences(value: string | null): PreferencesState {
  if (!value) return initialPreferences;
  try {
    const parsed: Record<string, unknown> = JSON.parse(value);
    return {
      theme: isThemePreference(parsed.theme) ? parsed.theme : "system",
      naturalChatPacing:
        typeof parsed.naturalChatPacing === "boolean"
          ? parsed.naturalChatPacing
          : true,
      showToolCalls:
        typeof parsed.showToolCalls === "boolean"
          ? parsed.showToolCalls
          : false,
      remoteNotifications:
        typeof parsed.remoteNotifications === "boolean"
          ? parsed.remoteNotifications
          : true,
      pushChatReplies:
        typeof parsed.pushChatReplies === "boolean"
          ? parsed.pushChatReplies
          : true,
      pushStatusChanges:
        typeof parsed.pushStatusChanges === "boolean"
          ? parsed.pushStatusChanges
          : true,
      notificationPreviews:
        typeof parsed.notificationPreviews === "boolean"
          ? parsed.notificationPreviews
          : false,
    };
  } catch {
    return initialPreferences;
  }
}
