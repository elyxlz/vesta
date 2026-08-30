import { create } from "zustand";

const STORAGE_KEY = "voice-activation";

// How the mic is triggered. Both dictate; "hold" confirms on release, "toggle" waits for
// the confirm button.
export type VoiceActivationMode = "toggle" | "hold";

interface VoiceActivationState {
  mode: VoiceActivationMode;
  setMode: (mode: VoiceActivationMode) => void;
}

function loadMode(): VoiceActivationMode {
  if (typeof localStorage === "undefined") return "toggle";
  const current = localStorage.getItem(STORAGE_KEY);
  return current === "hold" ? "hold" : "toggle";
}

export const useVoiceActivation = create<VoiceActivationState>((set) => ({
  mode: loadMode(),
  setMode: (mode) => {
    localStorage.setItem(STORAGE_KEY, mode);
    set({ mode });
  },
}));
