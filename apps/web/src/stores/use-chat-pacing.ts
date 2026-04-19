import { create } from "zustand";

const STORAGE_KEY = "chat-natural-pacing";

interface ChatPacingState {
  natural: boolean;
  setNatural: (natural: boolean) => void;
}

export const useChatPacing = create<ChatPacingState>((set) => ({
  natural: localStorage.getItem(STORAGE_KEY) !== "off",
  setNatural: (natural) => {
    localStorage.setItem(STORAGE_KEY, natural ? "on" : "off");
    set({ natural });
  },
}));
