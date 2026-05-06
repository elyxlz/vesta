import { create } from "zustand";

const STORAGE_KEY = "vesta:mode";

export type AppMode = "simple" | "advanced";

interface AppModeState {
  mode: AppMode;
  setMode: (mode: AppMode) => void;
}

function loadInitial(): AppMode {
  if (typeof localStorage === "undefined") return "simple";
  return localStorage.getItem(STORAGE_KEY) === "advanced"
    ? "advanced"
    : "simple";
}

export const useAppMode = create<AppModeState>((set) => ({
  mode: loadInitial(),
  setMode: (mode) => {
    localStorage.setItem(STORAGE_KEY, mode);
    set({ mode });
  },
}));
