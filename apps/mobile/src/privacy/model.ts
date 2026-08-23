import type { AppStateStatus } from "react-native";

export interface PrivacySettings {
  appLockEnabled: boolean;
  hideAppSwitcherPreview: boolean;
}

export const initialPrivacySettings: PrivacySettings = {
  appLockEnabled: false,
  hideAppSwitcherPreview: false,
};

export function readPrivacySettings(value: string | null): PrivacySettings {
  if (!value) return initialPrivacySettings;
  try {
    const parsed: Record<string, unknown> = JSON.parse(value);
    return {
      appLockEnabled:
        typeof parsed.appLockEnabled === "boolean"
          ? parsed.appLockEnabled
          : false,
      // The app switcher toggle is withheld from Settings for now, so a
      // stored value is ignored until it returns.
      hideAppSwitcherPreview: false,
    };
  } catch {
    return initialPrivacySettings;
  }
}

export function protectsAppSwitcher(settings: PrivacySettings): boolean {
  return settings.appLockEnabled || settings.hideAppSwitcherPreview;
}

export function locksApp(state: AppStateStatus): boolean {
  return state === "background";
}

export function blocksProtectedContent(
  hydrated: boolean,
  locked: boolean,
  initializationFailed = false,
): boolean {
  return !hydrated || locked || initializationFailed;
}
