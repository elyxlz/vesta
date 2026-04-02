import { create } from "zustand";
import type { ListEntry } from "@/lib/types";

export type View =
  | "loading"
  | "connect"
  | "home"
  | "agent-detail"
  | "agent-chat"
  | "agent-console";

interface AppState {
  view: View;
  connected: boolean;
  selectedAgent: string | null;
  agents: ListEntry[];
  version: string;

  setView: (view: View) => void;
  setConnected: (connected: boolean) => void;
  setSelectedAgent: (name: string | null) => void;
  setAgents: (agents: ListEntry[]) => void;
  setVersion: (version: string) => void;
  navigateToAgent: (name: string) => void;
  navigateToChat: (name: string) => void;
  navigateToConsole: (name: string) => void;
  navigateHome: () => void;
  disconnect: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  view: "loading",
  connected: false,
  selectedAgent: null,
  agents: [],
  version: "",

  setView: (view) => set({ view }),
  setConnected: (connected) => set({ connected }),
  setSelectedAgent: (name) => set({ selectedAgent: name }),
  setAgents: (agents) => set({ agents }),
  setVersion: (version) => set({ version }),

  navigateToAgent: (name) =>
    set({ view: "agent-detail", selectedAgent: name }),

  navigateToChat: (name) =>
    set({ view: "agent-chat", selectedAgent: name }),

  navigateToConsole: (name) =>
    set({ view: "agent-console", selectedAgent: name }),

  navigateHome: () => set({ view: "home", selectedAgent: null }),

  disconnect: () => {
    set({
      view: "connect",
      connected: false,
      selectedAgent: null,
      agents: [],
      version: "",
    });
  },
}));
