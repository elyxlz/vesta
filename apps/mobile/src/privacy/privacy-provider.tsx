import {
  createContext,
  use,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AppState } from "react-native";
import * as LocalAuthentication from "expo-local-authentication";
import * as ScreenCapture from "expo-screen-capture";
import * as SecureStore from "expo-secure-store";
import {
  initialPrivacySettings,
  locksApp,
  protectsAppSwitcher,
  readPrivacySettings,
  type PrivacySettings,
} from "./model";

const PRIVACY_SETTINGS_KEY = "vesta.privacy.v1";
const SCREEN_CAPTURE_KEY = "vesta-app-switcher";
const IS_IOS = process.env.EXPO_OS === "ios";
const IS_ANDROID = process.env.EXPO_OS === "android";
const CANCELLED_AUTH_ERRORS = new Set([
  "user_cancel",
  "app_cancel",
  "system_cancel",
]);

interface PrivacyValue extends PrivacySettings {
  hydrated: boolean;
  locked: boolean;
  authenticating: boolean;
  authenticationName: string;
  initializationError: string | null;
  unlockError: string | null;
  retryInitialization: () => void;
  unlock: () => Promise<boolean>;
  setAppLockEnabled: (enabled: boolean) => Promise<boolean>;
  setHideAppSwitcherPreview: (enabled: boolean) => Promise<void>;
}

const PrivacyContext = createContext<PrivacyValue | null>(null);

function authenticationName(types: LocalAuthentication.AuthenticationType[]) {
  if (
    types.includes(LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION)
  ) {
    return IS_IOS ? "Face ID" : "face unlock";
  }
  if (types.includes(LocalAuthentication.AuthenticationType.FINGERPRINT)) {
    return IS_IOS ? "Touch ID" : "fingerprint";
  }
  return "device authentication";
}

function authenticationError(error: string): string {
  if (error === "not_enrolled") {
    return "Set up Face ID, Touch ID, or fingerprint authentication in your device settings first.";
  }
  if (error === "not_available") {
    return "Device authentication is not available on this device.";
  }
  if (error === "passcode_not_set") {
    return "Set a device passcode before enabling App Lock.";
  }
  if (error === "lockout") {
    return "Device authentication is temporarily locked. Unlock your device and try again.";
  }
  return "Vesta could not verify your identity. Please try again.";
}

async function applyAppSwitcherProtection(
  settings: PrivacySettings,
): Promise<void> {
  const protectedPreview = protectsAppSwitcher(settings);
  if (IS_IOS) {
    if (protectedPreview) {
      await ScreenCapture.enableAppSwitcherProtectionAsync(1);
    } else {
      await ScreenCapture.disableAppSwitcherProtectionAsync();
    }
  } else if (IS_ANDROID) {
    if (protectedPreview) {
      await ScreenCapture.preventScreenCaptureAsync(SCREEN_CAPTURE_KEY);
    } else {
      await ScreenCapture.allowScreenCaptureAsync(SCREEN_CAPTURE_KEY);
    }
  }
}

export function PrivacyProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState(initialPrivacySettings);
  const [hydrated, setHydrated] = useState(false);
  const [hydrationRevision, setHydrationRevision] = useState(0);
  const [locked, setLocked] = useState(true);
  const [authenticating, setAuthenticating] = useState(false);
  const [authName, setAuthName] = useState("device authentication");
  const [initializationError, setInitializationError] = useState<string | null>(
    null,
  );
  const [unlockError, setUnlockError] = useState<string | null>(null);
  const settingsRef = useRef(settings);
  const lockedRef = useRef(locked);
  const authenticatingRef = useRef(false);
  const privacyReadyRef = useRef(false);

  const updateLocked = useCallback((value: boolean) => {
    lockedRef.current = value;
    setLocked(value);
    if (!value) setUnlockError(null);
  }, []);

  useEffect(() => {
    let active = true;

    const initialize = async () => {
      try {
        const stored = await SecureStore.getItemAsync(PRIVACY_SETTINGS_KEY);
        if (!active) return;
        const next = readPrivacySettings(stored);

        try {
          await applyAppSwitcherProtection(next);
        } catch (cause) {
          if (protectsAppSwitcher(next)) throw cause;
          console.warn("Could not clear app-switcher protection:", cause);
        }
        if (!active) return;

        settingsRef.current = next;
        setSettings(next);
        updateLocked(next.appLockEnabled);
        privacyReadyRef.current = true;
      } catch (cause) {
        if (!active) return;
        console.warn("Could not load privacy settings:", cause);
        setInitializationError(
          "Vesta could not safely load your privacy settings.",
        );
        updateLocked(true);
      } finally {
        if (active) setHydrated(true);
      }
    };

    void initialize();
    return () => {
      active = false;
    };
  }, [hydrationRevision, updateLocked]);

  const retryInitialization = useCallback(() => {
    privacyReadyRef.current = false;
    setHydrated(false);
    setInitializationError(null);
    updateLocked(true);
    setHydrationRevision((revision) => revision + 1);
  }, [updateLocked]);

  useEffect(() => {
    let active = true;
    void LocalAuthentication.supportedAuthenticationTypesAsync()
      .then((types) => {
        if (active) setAuthName(authenticationName(types));
      })
      .catch((cause: unknown) =>
        console.warn("Could not inspect device authentication:", cause),
      );
    return () => {
      active = false;
    };
  }, []);

  const updateSettings = useCallback(
    async (patch: Partial<PrivacySettings>) => {
      const previous = settingsRef.current;
      const next = { ...previous, ...patch };
      const nextProtectsPreview = protectsAppSwitcher(next);

      try {
        // Establish protection before recording that it is enabled. When disabling,
        // record the choice first so an interruption can only leave extra protection behind.
        if (nextProtectsPreview) await applyAppSwitcherProtection(next);
        await SecureStore.setItemAsync(
          PRIVACY_SETTINGS_KEY,
          JSON.stringify(next),
          { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY },
        );
        if (!nextProtectsPreview) await applyAppSwitcherProtection(next);
      } catch (cause) {
        try {
          await applyAppSwitcherProtection(previous);
        } catch (rollbackCause) {
          console.warn(
            "Could not restore native app-switcher protection:",
            rollbackCause,
          );
        }
        try {
          await SecureStore.setItemAsync(
            PRIVACY_SETTINGS_KEY,
            JSON.stringify(previous),
            { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY },
          );
        } catch (rollbackCause) {
          console.warn(
            "Could not roll back privacy settings after native protection failed:",
            rollbackCause,
          );
        }
        console.warn("Could not update privacy settings:", cause);
        throw new Error(
          "Vesta could not save or apply privacy settings on this device.",
        );
      }

      settingsRef.current = next;
      setSettings(next);
    },
    [],
  );

  const authenticate = useCallback(async () => {
    if (authenticatingRef.current) return null;
    authenticatingRef.current = true;
    setAuthenticating(true);
    try {
      return await LocalAuthentication.authenticateAsync({
        promptMessage: "Unlock Vesta",
        promptSubtitle: "Authenticate to continue",
        cancelLabel: "Cancel",
        fallbackLabel: "Use Passcode",
        biometricsSecurityLevel: "strong",
      });
    } finally {
      authenticatingRef.current = false;
      setAuthenticating(false);
    }
  }, []);

  const unlock = useCallback(async (): Promise<boolean> => {
    if (!privacyReadyRef.current) return false;
    if (!settingsRef.current.appLockEnabled) {
      updateLocked(false);
      return true;
    }
    if (!lockedRef.current) return true;
    try {
      const result = await authenticate();
      if (!result) return false;
      if (result.success) {
        updateLocked(false);
        return true;
      }
      if (!CANCELLED_AUTH_ERRORS.has(result.error)) {
        setUnlockError(authenticationError(result.error));
      }
      return false;
    } catch (cause) {
      console.warn("Could not authenticate:", cause);
      setUnlockError("Device authentication is currently unavailable.");
      return false;
    }
  }, [authenticate, updateLocked]);

  const setAppLockEnabled = useCallback(
    async (enabled: boolean): Promise<boolean> => {
      if (!enabled) {
        await updateSettings({ appLockEnabled: false });
        updateLocked(false);
        return true;
      }

      const [hasHardware, enrolled] = await Promise.all([
        LocalAuthentication.hasHardwareAsync(),
        LocalAuthentication.isEnrolledAsync(),
      ]);
      if (!hasHardware) {
        throw new Error(
          "This device does not support Face ID, Touch ID, or fingerprint authentication.",
        );
      }
      if (!enrolled) {
        throw new Error(
          "Set up Face ID, Touch ID, or fingerprint authentication in your device settings first.",
        );
      }

      const result = await authenticate();
      if (!result || !result.success) {
        if (result && !CANCELLED_AUTH_ERRORS.has(result.error)) {
          throw new Error(authenticationError(result.error));
        }
        return false;
      }
      await updateSettings({ appLockEnabled: true });
      updateLocked(false);
      return true;
    },
    [authenticate, updateLocked, updateSettings],
  );

  const setHideAppSwitcherPreview = useCallback(
    (enabled: boolean) => updateSettings({ hideAppSwitcherPreview: enabled }),
    [updateSettings],
  );

  useEffect(() => {
    if (
      !hydrated ||
      initializationError ||
      !privacyReadyRef.current ||
      !settings.appLockEnabled
    ) {
      return;
    }
    if (AppState.currentState === "active" && lockedRef.current) {
      void unlock();
    }
  }, [hydrated, initializationError, settings.appLockEnabled, unlock]);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      if (!privacyReadyRef.current) return;
      if (locksApp(state) && settingsRef.current.appLockEnabled) {
        updateLocked(true);
      } else if (
        state === "active" &&
        settingsRef.current.appLockEnabled &&
        lockedRef.current
      ) {
        void unlock();
      }
    });
    return () => subscription.remove();
  }, [unlock, updateLocked]);

  const value = useMemo<PrivacyValue>(
    () => ({
      ...settings,
      hydrated,
      locked,
      authenticating,
      authenticationName: authName,
      initializationError,
      unlockError,
      retryInitialization,
      unlock,
      setAppLockEnabled,
      setHideAppSwitcherPreview,
    }),
    [
      settings,
      hydrated,
      locked,
      authenticating,
      authName,
      initializationError,
      unlockError,
      retryInitialization,
      unlock,
      setAppLockEnabled,
      setHideAppSwitcherPreview,
    ],
  );

  return (
    <PrivacyContext.Provider value={value}>{children}</PrivacyContext.Provider>
  );
}

export function usePrivacy(): PrivacyValue {
  const value = use(PrivacyContext);
  if (!value) {
    throw new Error("usePrivacy must be used within PrivacyProvider");
  }
  return value;
}
