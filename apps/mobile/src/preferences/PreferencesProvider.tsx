import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useColorScheme } from "react-native";
import { darkColors, lightColors, type AppColors } from "@/theme/colors";
import {
  getNaturalChatPacingForAgent,
  getShowToolCallsForAgent,
  initialPreferences,
  readStoredPreferences,
  type PreferencesState,
} from "./model";

const PREFERENCES_KEY = "vesta.preferences.v1";

export type { ThemePreference } from "./model";

interface PreferencesValue extends PreferencesState {
  hydrated: boolean;
  dark: boolean;
  colors: AppColors;
  update: (patch: Partial<PreferencesState>) => Promise<void>;
  showToolCallsForAgent: (agentName: string) => boolean;
  setShowToolCallsForAgent: (
    agentName: string,
    showToolCalls: boolean,
  ) => Promise<void>;
  naturalChatPacingForAgent: (agentName: string) => boolean;
  setNaturalChatPacingForAgent: (
    agentName: string,
    naturalChatPacing: boolean,
  ) => Promise<void>;
}

const PreferencesContext = createContext<PreferencesValue | null>(null);

const ThemeOverrideContext = createContext<{
  dark: boolean;
  colors: AppColors;
} | null>(null);

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const systemScheme = useColorScheme();
  const [preferences, setPreferences] =
    useState<PreferencesState>(initialPreferences);
  const [hydrated, setHydrated] = useState(false);
  const preferencesRef = useRef(preferences);
  const writeChainRef = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    let active = true;
    void AsyncStorage.getItem(PREFERENCES_KEY)
      .then((stored) => {
        if (!active) return;
        const next = readStoredPreferences(stored);
        preferencesRef.current = next;
        setPreferences(next);
      })
      .catch((cause: unknown) => {
        console.warn("Could not load preferences:", cause);
      })
      .finally(() => {
        if (active) setHydrated(true);
      });
    return () => {
      active = false;
    };
  }, []);

  const update = useCallback(
    (patch: Partial<PreferencesState>): Promise<void> => {
      const next = { ...preferencesRef.current, ...patch };
      preferencesRef.current = next;
      setPreferences(next);
      const write = writeChainRef.current.then(() =>
        AsyncStorage.setItem(PREFERENCES_KEY, JSON.stringify(next)),
      );
      writeChainRef.current = write.catch(() => undefined);
      return write;
    },
    [],
  );

  const showToolCallsForAgent = useCallback(
    (agentName: string) =>
      getShowToolCallsForAgent(preferencesRef.current, agentName),
    [],
  );

  const setShowToolCallsForAgent = useCallback(
    (agentName: string, showToolCalls: boolean) =>
      update({
        showToolCallsByAgent: {
          ...preferencesRef.current.showToolCallsByAgent,
          [agentName]: showToolCalls,
        },
      }),
    [update],
  );

  const naturalChatPacingForAgent = useCallback(
    (agentName: string) =>
      getNaturalChatPacingForAgent(preferencesRef.current, agentName),
    [],
  );

  const setNaturalChatPacingForAgent = useCallback(
    (agentName: string, naturalChatPacing: boolean) =>
      update({
        naturalChatPacingByAgent: {
          ...preferencesRef.current.naturalChatPacingByAgent,
          [agentName]: naturalChatPacing,
        },
      }),
    [update],
  );

  const dark =
    preferences.theme === "system"
      ? systemScheme !== "light"
      : preferences.theme === "dark";
  const value = useMemo<PreferencesValue>(
    () => ({
      ...preferences,
      hydrated,
      dark,
      colors: dark ? darkColors : lightColors,
      update,
      showToolCallsForAgent,
      setShowToolCallsForAgent,
      naturalChatPacingForAgent,
      setNaturalChatPacingForAgent,
    }),
    [
      preferences,
      hydrated,
      dark,
      update,
      showToolCallsForAgent,
      setShowToolCallsForAgent,
      naturalChatPacingForAgent,
      setNaturalChatPacingForAgent,
    ],
  );

  return (
    <PreferencesContext.Provider value={value}>
      {children}
    </PreferencesContext.Provider>
  );
}

export function usePreferences(): PreferencesValue {
  const value = useContext(PreferencesContext);
  const override = useContext(ThemeOverrideContext);
  if (!value) {
    throw new Error("usePreferences must be used within PreferencesProvider");
  }
  return override ? { ...value, ...override } : value;
}

export function ThemeOverrideProvider({
  children,
  theme,
}: {
  children: ReactNode;
  theme: "light" | "dark";
}) {
  const value =
    theme === "light"
      ? { dark: false, colors: lightColors }
      : { dark: true, colors: darkColors };
  return (
    <ThemeOverrideContext.Provider value={value}>
      {children}
    </ThemeOverrideContext.Provider>
  );
}
