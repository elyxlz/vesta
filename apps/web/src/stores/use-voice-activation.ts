import { create } from "zustand";

const STORAGE_KEY = "voice-activation";

export type VoiceActivationMode = "toggle" | "hold";

interface VoiceActivationState {
  mode: VoiceActivationMode;
  setMode: (mode: VoiceActivationMode) => void;
}

function loadInitial(): VoiceActivationMode {
  if (typeof localStorage === "undefined") return "toggle";
  // Migrate the old key if it's the only one present.
  const legacy = localStorage.getItem("spacebar-mode");
  const current = localStorage.getItem(STORAGE_KEY) ?? legacy;
  return current === "hold" ? "hold" : "toggle";
}

export const useVoiceActivation = create<VoiceActivationState>((set) => ({
  mode: loadInitial(),
  setMode: (mode) => {
    localStorage.setItem(STORAGE_KEY, mode);
    set({ mode });
  },
}));
