import {
  createContext,
  use,
  useCallback,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import * as Linking from "expo-linking";

interface PrivacyValue {
  appLockEnabled: boolean;
  hideAppSwitcherPreview: boolean;
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
const initializationMessage =
  "Vesta could not safely load your privacy settings.";
const unlockMessage =
  "Device authentication is temporarily locked. Unlock your device and try again.";
const launchUrl = Linking.getLinkingURL();
const startsUnlocked =
  launchUrl !== null &&
  Linking.parse(launchUrl).queryParams?.visualPrivacy === "unlocked";

export function PrivacyProvider({ children }: { children: ReactNode }) {
  const [locked, setLocked] = useState(!startsUnlocked);
  const [authenticating, setAuthenticating] = useState(false);
  const [initializationError, setInitializationError] = useState<string | null>(
    startsUnlocked ? null : initializationMessage,
  );
  const [unlockError, setUnlockError] = useState<string | null>(null);

  const retryInitialization = useCallback(() => {
    setInitializationError(null);
    setUnlockError(null);
    setLocked(true);
  }, []);

  const unlock = useCallback(async (): Promise<boolean> => {
    setAuthenticating(true);
    await new Promise((resolve) => setTimeout(resolve, 300));
    setAuthenticating(false);
    setUnlockError(unlockMessage);
    return false;
  }, []);

  const value = useMemo<PrivacyValue>(
    () => ({
      appLockEnabled: true,
      hideAppSwitcherPreview: true,
      hydrated: true,
      locked,
      authenticating,
      authenticationName: "Face ID",
      initializationError,
      unlockError,
      retryInitialization,
      unlock,
      setAppLockEnabled: async (enabled) => {
        setLocked(enabled);
        return true;
      },
      setHideAppSwitcherPreview: async () => undefined,
    }),
    [
      authenticating,
      initializationError,
      locked,
      retryInitialization,
      unlock,
      unlockError,
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
