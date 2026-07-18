export type ThemePreference = "system" | "light" | "dark";

export interface PreferencesState {
  theme: ThemePreference;
  naturalChatPacingDefault: boolean;
  naturalChatPacingByAgent: Record<string, boolean>;
  showToolCallsDefault: boolean;
  showToolCallsByAgent: Record<string, boolean>;
  showNotificationsPage: boolean;
  showLogsPage: boolean;
  remoteNotifications: boolean;
  pushChatReplies: boolean;
  pushStatusChanges: boolean;
  notificationPreviews: boolean;
}

export const initialPreferences: PreferencesState = {
  theme: "system",
  naturalChatPacingDefault: true,
  naturalChatPacingByAgent: {},
  showToolCallsDefault: false,
  showToolCallsByAgent: {},
  showNotificationsPage: false,
  showLogsPage: false,
  remoteNotifications: true,
  pushChatReplies: true,
  pushStatusChanges: true,
  notificationPreviews: false,
};

function isThemePreference(value: unknown): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

function readBooleanRecord(value: unknown): Record<string, boolean> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};

  return Object.fromEntries(
    Object.entries(value).filter(
      (entry): entry is [string, boolean] => typeof entry[1] === "boolean",
    ),
  );
}

export function getShowToolCallsForAgent(
  preferences: Pick<
    PreferencesState,
    "showToolCallsDefault" | "showToolCallsByAgent"
  >,
  agentName: string,
): boolean {
  return (
    preferences.showToolCallsByAgent[agentName] ??
    preferences.showToolCallsDefault
  );
}

export function getNaturalChatPacingForAgent(
  preferences: Pick<
    PreferencesState,
    "naturalChatPacingDefault" | "naturalChatPacingByAgent"
  >,
  agentName: string,
): boolean {
  return (
    preferences.naturalChatPacingByAgent[agentName] ??
    preferences.naturalChatPacingDefault
  );
}

export function readStoredPreferences(value: string | null): PreferencesState {
  if (!value) return initialPreferences;
  try {
    const parsed: Record<string, unknown> = JSON.parse(value);
    return {
      theme: isThemePreference(parsed.theme) ? parsed.theme : "system",
      naturalChatPacingDefault:
        typeof parsed.naturalChatPacingDefault === "boolean"
          ? parsed.naturalChatPacingDefault
          : typeof parsed.naturalChatPacing === "boolean"
            ? parsed.naturalChatPacing
            : true,
      naturalChatPacingByAgent: readBooleanRecord(
        parsed.naturalChatPacingByAgent,
      ),
      showToolCallsDefault:
        typeof parsed.showToolCallsDefault === "boolean"
          ? parsed.showToolCallsDefault
          : typeof parsed.showToolCalls === "boolean"
            ? parsed.showToolCalls
            : false,
      showToolCallsByAgent: readBooleanRecord(parsed.showToolCallsByAgent),
      showNotificationsPage:
        typeof parsed.showNotificationsPage === "boolean"
          ? parsed.showNotificationsPage
          : false,
      showLogsPage:
        typeof parsed.showLogsPage === "boolean" ? parsed.showLogsPage : false,
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
