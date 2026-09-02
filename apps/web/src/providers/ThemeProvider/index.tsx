import * as React from "react";
import { native } from "@/lib/native";
import { useMediaQuery } from "@/hooks/use-media-query";
import {
  ThemeProviderContext,
  type ResolvedTheme,
  type Theme,
  type ThemeProviderState,
} from "./context";

interface ThemeProviderProps {
  children: React.ReactNode;
  defaultTheme?: Theme;
  storageKey?: string;
  disableTransitionOnChange?: boolean;
}

const COLOR_SCHEME_QUERY = "(prefers-color-scheme: dark)";
const THEME_VALUES: readonly Theme[] = ["dark", "light", "system"];

function isTheme(value: string | null): value is Theme {
  return THEME_VALUES.some((theme) => theme === value);
}

function disableTransitionsTemporarily() {
  const style = document.createElement("style");
  style.appendChild(
    document.createTextNode(
      "*,*::before,*::after{-webkit-transition:none!important;transition:none!important}",
    ),
  );
  document.head.appendChild(style);

  return () => {
    window.getComputedStyle(document.body);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        style.remove();
      });
    });
  };
}

export function ThemeProvider({
  children,
  defaultTheme = "system",
  storageKey = "theme",
  disableTransitionOnChange = true,
  ...props
}: ThemeProviderProps) {
  const [theme, setThemeState] = React.useState<Theme>(() => {
    const storedTheme = localStorage.getItem(storageKey);
    if (isTheme(storedTheme)) {
      return storedTheme;
    }

    return defaultTheme;
  });

  // The resolved theme is derived: the chosen theme, or the OS scheme while following "system".
  const systemDark = useMediaQuery(COLOR_SCHEME_QUERY);
  const resolvedTheme: ResolvedTheme =
    theme === "system" ? (systemDark ? "dark" : "light") : theme;

  const setTheme = (nextTheme: Theme) => {
    localStorage.setItem(storageKey, nextTheme);
    setThemeState(nextTheme);
  };

  React.useEffect(() => {
    const root = document.documentElement;
    const restoreTransitions = disableTransitionOnChange
      ? disableTransitionsTemporarily()
      : null;

    root.classList.remove("light", "dark");
    root.classList.add(resolvedTheme);
    root.style.colorScheme = resolvedTheme;

    native.setNativeTheme(theme === "system" ? "system" : resolvedTheme);

    if (restoreTransitions) {
      restoreTransitions();
    }
  }, [theme, resolvedTheme, disableTransitionOnChange]);

  const cycleTheme = React.useCallback(() => {
    setThemeState((currentTheme) => {
      const nextTheme =
        currentTheme === "dark"
          ? "light"
          : currentTheme === "light"
            ? "dark"
            : window.matchMedia(COLOR_SCHEME_QUERY).matches
              ? "light"
              : "dark";

      localStorage.setItem(storageKey, nextTheme);
      return nextTheme;
    });
  }, [storageKey]);

  React.useEffect(() => {
    const handleStorageChange = (event: StorageEvent) => {
      if (event.storageArea !== localStorage) {
        return;
      }

      if (event.key !== storageKey) {
        return;
      }

      if (isTheme(event.newValue)) {
        setThemeState(event.newValue);
        return;
      }

      setThemeState(defaultTheme);
    };

    window.addEventListener("storage", handleStorageChange);

    return () => {
      window.removeEventListener("storage", handleStorageChange);
    };
  }, [defaultTheme, storageKey]);

  const value: ThemeProviderState = {
    theme,
    resolvedTheme,
    setTheme,
    cycleTheme,
  };

  return (
    <ThemeProviderContext.Provider {...props} value={value}>
      {children}
    </ThemeProviderContext.Provider>
  );
}
