import { create } from "zustand";

export type View =
  | "loading"
  | "connect"
  | "home"
  | "agent-detail"
  | "agent-chat"
  | "agent-console";

interface NavigationState {
  view: View;
  selectedAgent: string | null;

  setView: (view: View) => void;
  navigateToAgent: (name: string) => void;
  navigateToChat: (name: string) => void;
  navigateToConsole: (name: string) => void;
  navigateHome: () => void;
  navigateToConnect: () => void;
}

export const useNavigation = create<NavigationState>((set) => ({
  view: "loading",
  selectedAgent: null,

  setView: (view) => set({ view }),

  navigateToAgent: (name) =>
    set({ view: "agent-detail", selectedAgent: name }),

  navigateToChat: (name) =>
    set({ view: "agent-chat", selectedAgent: name }),

  navigateToConsole: (name) =>
    set({ view: "agent-console", selectedAgent: name }),

  navigateHome: () => set({ view: "home", selectedAgent: null }),

  navigateToConnect: () => set({ view: "connect", selectedAgent: null }),
}));
