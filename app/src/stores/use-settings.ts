import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

export interface CustomVoice {
  id: string;
  name: string;
}

interface Settings {
  voiceAutoSend: boolean;
  speechEnabled: boolean;
  ttsVoiceId: string;
  sttEotThreshold: number;
  sttEotTimeoutMs: number;
  customVoices: CustomVoice[];
}

interface SettingsState extends Settings {
  set: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  addCustomVoice: (voice: CustomVoice) => void;
  removeCustomVoice: (id: string) => void;
}

const defaults: Settings = {
  voiceAutoSend: true,
  speechEnabled: false,
  ttsVoiceId: "FGY2WhTYpPnrIDTdsKH5",
  sttEotThreshold: 0.8,
  sttEotTimeoutMs: 10000,
  customVoices: [],
};

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      ...defaults,
      set: (key, value) => set({ [key]: value } as Partial<SettingsState>),
      addCustomVoice: (voice) =>
        set((state) => {
          if (state.customVoices.some((v) => v.id === voice.id)) return state;
          return { customVoices: [...state.customVoices, voice] };
        }),
      removeCustomVoice: (id) =>
        set((state) => ({
          customVoices: state.customVoices.filter((v) => v.id !== id),
          ttsVoiceId: state.ttsVoiceId === id ? defaults.ttsVoiceId : state.ttsVoiceId,
        })),
    }),
    {
      name: "vesta-settings",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        voiceAutoSend: state.voiceAutoSend,
        speechEnabled: state.speechEnabled,
        ttsVoiceId: state.ttsVoiceId,
        sttEotThreshold: state.sttEotThreshold,
        sttEotTimeoutMs: state.sttEotTimeoutMs,
        customVoices: state.customVoices,
      }),
    },
  ),
);
