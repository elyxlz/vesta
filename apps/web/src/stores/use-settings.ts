import { create } from "zustand";
import { fetchUsage, type Utilization } from "@/api/agents";

interface SettingsState {
  utilization: Record<string, Utilization>;
  usageLoading: boolean;
  usageError: boolean;
  refreshUsage: (agentName: string) => void;
}

export const useSettings = create<SettingsState>((set, get) => ({
  utilization: {},
  usageLoading: false,
  usageError: false,

  refreshUsage: (agentName: string) => {
    set({ usageLoading: true, usageError: false });
    fetchUsage(agentName)
      .then((data) => {
        set({ utilization: { ...get().utilization, [agentName]: data } });
      })
      .catch(() => {
        set({ usageError: true });
      })
      .finally(() => {
        set({ usageLoading: false });
      });
  },
}));
