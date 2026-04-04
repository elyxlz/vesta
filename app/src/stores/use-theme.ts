import { create } from "zustand";

export type Theme = "light" | "dark" | "system";

function getSystemTheme(): "light" | "dark" {
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem("vesta-theme");
    if (stored === "light" || stored === "dark" || stored === "system")
      return stored;
  } catch {
    // ignore
  }
  return "system";
}

function applyTheme(theme: Theme) {
  const resolved = theme === "system" ? getSystemTheme() : theme;
  document.documentElement.classList.toggle("dark", resolved === "dark");
}

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  resolved: () => "light" | "dark";
}

export const useTheme = create<ThemeState>((set, get) => {
  const initial = getStoredTheme();
  applyTheme(initial);

  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      if (get().theme === "system") applyTheme("system");
    });

  return {
    theme: initial,

    setTheme: (theme) => {
      localStorage.setItem("vesta-theme", theme);
      applyTheme(theme);
      set({ theme });
    },

    resolved: () => {
      const t = get().theme;
      return t === "system" ? getSystemTheme() : t;
    },
  };
});
