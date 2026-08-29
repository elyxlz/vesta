export type ThemePreference = "system" | "light" | "dark";

// The AsyncStorage key the preferences persist under; read headless by the background report too.
export const PREFERENCES_KEY = "vesta.preferences.v1";

export interface PreferencesState {
  theme: ThemePreference;
  naturalChatPacingByAgent: Record<string, boolean>;
  showChatPage: boolean;
  showDashboardPage: boolean;
  showNotificationsPage: boolean;
  showLogsPage: boolean;
  remoteNotifications: boolean;
  pushChatReplies: boolean;
  notificationPreviews: boolean;
  // Report the phone's position (and the place the OS geocodes for it) to the gateway, so the
  // agents learn where the user is. On by default; the OS location grant is the consent, and the
  // Privacy toggle is the per-device off switch (off retracts the stored position).
  shareLocation: boolean;
}

export const initialPreferences: PreferencesState = {
  theme: "system",
  naturalChatPacingByAgent: {},
  showChatPage: true,
  showDashboardPage: true,
  showNotificationsPage: false,
  showLogsPage: false,
  remoteNotifications: true,
  pushChatReplies: true,
  notificationPreviews: false,
  shareLocation: true,
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

export function getNaturalChatPacingForAgent(
  preferences: Pick<PreferencesState, "naturalChatPacingByAgent">,
  agentName: string,
): boolean {
  return preferences.naturalChatPacingByAgent[agentName] ?? true;
}

export function readStoredPreferences(value: string | null): PreferencesState {
  if (!value) return initialPreferences;
  try {
    const parsed: Record<string, unknown> = JSON.parse(value);
    return {
      theme: isThemePreference(parsed.theme) ? parsed.theme : "system",
      naturalChatPacingByAgent: readBooleanRecord(
        parsed.naturalChatPacingByAgent,
      ),
      showChatPage:
        typeof parsed.showChatPage === "boolean" ? parsed.showChatPage : true,
      showDashboardPage:
        typeof parsed.showDashboardPage === "boolean"
          ? parsed.showDashboardPage
          : true,
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
      notificationPreviews:
        typeof parsed.notificationPreviews === "boolean"
          ? parsed.notificationPreviews
          : false,
      shareLocation:
        typeof parsed.shareLocation === "boolean" ? parsed.shareLocation : true,
    };
  } catch {
    return initialPreferences;
  }
}
