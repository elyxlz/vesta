import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

interface Settings {
  voiceAutoSend: boolean;
  speechEnabled: boolean;
}

interface SettingsState extends Settings {
  set: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
}

const defaults: Settings = {
  voiceAutoSend: true,
  speechEnabled: false,
};

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      ...defaults,
      set: (key, value) => set({ [key]: value } as Partial<SettingsState>),
    }),
    {
      name: "vesta-settings",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        voiceAutoSend: state.voiceAutoSend,
        speechEnabled: state.speechEnabled,
      }),
    },
  ),
);
