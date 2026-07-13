import { create } from "zustand";

const STORAGE_KEY = "chat-show-tool-calls";

interface ShowToolCallsState {
  showToolCalls: boolean;
  setShowToolCalls: (value: boolean | ((prev: boolean) => boolean)) => void;
}

export const useShowToolCalls = create<ShowToolCallsState>((set, get) => ({
  showToolCalls: localStorage.getItem(STORAGE_KEY) === "on",
  setShowToolCalls: (value) => {
    const next =
      typeof value === "function" ? value(get().showToolCalls) : value;
    localStorage.setItem(STORAGE_KEY, next ? "on" : "off");
    set({ showToolCalls: next });
  },
}));
