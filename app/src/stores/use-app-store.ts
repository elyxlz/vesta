import { create } from "zustand";
import type { ListEntry } from "@/lib/types";
import { useNavigation } from "./use-navigation";

interface AppState {
  connected: boolean;
  agents: ListEntry[];
  version: string;

  setConnected: (connected: boolean) => void;
  setAgents: (agents: ListEntry[]) => void;
  setVersion: (version: string) => void;
  disconnect: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  connected: false,
  agents: [],
  version: "",

  setConnected: (connected) => set({ connected }),
  setAgents: (agents) => set({ agents }),
  setVersion: (version) => set({ version }),

  disconnect: () => {
    set({ connected: false, agents: [], version: "" });
    useNavigation.getState().navigateToConnect();
  },
}));
