import { create } from "zustand";

const STORAGE_KEY = "voice-activation";
const IDLE_TIMEOUT_KEY = "voice-toggle-idle-timeout-ms";

export type VoiceActivationMode = "toggle" | "hold";

interface VoiceActivationState {
  mode: VoiceActivationMode;
  toggleIdleTimeoutMs: number | null;
  setMode: (mode: VoiceActivationMode) => void;
  setToggleIdleTimeoutMs: (ms: number | null) => void;
}

function loadMode(): VoiceActivationMode {
  if (typeof localStorage === "undefined") return "toggle";
  // Migrate the old key if it's the only one present.
  const legacy = localStorage.getItem("spacebar-mode");
  const current = localStorage.getItem(STORAGE_KEY) ?? legacy;
  return current === "hold" ? "hold" : "toggle";
}

function loadIdleTimeout(): number | null {
  if (typeof localStorage === "undefined") return null;
  const raw = localStorage.getItem(IDLE_TIMEOUT_KEY);
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export const useVoiceActivation = create<VoiceActivationState>((set) => ({
  mode: loadMode(),
  toggleIdleTimeoutMs: loadIdleTimeout(),
  setMode: (mode) => {
    localStorage.setItem(STORAGE_KEY, mode);
    set({ mode });
  },
  setToggleIdleTimeoutMs: (ms) => {
    if (ms === null) localStorage.removeItem(IDLE_TIMEOUT_KEY);
    else localStorage.setItem(IDLE_TIMEOUT_KEY, String(ms));
    set({ toggleIdleTimeoutMs: ms });
  },
}));
