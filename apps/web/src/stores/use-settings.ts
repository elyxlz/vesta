import { create } from "zustand";
import { fetchUsage, type Utilization } from "@/api/agents";

interface SettingsState {
  utilization: Record<string, Utilization>;
  usageLoading: Record<string, boolean>;
  usageError: Record<string, boolean>;
  refreshUsage: (agentName: string) => void;
}

export const useSettings = create<SettingsState>((set) => ({
  utilization: {},
  usageLoading: {},
  usageError: {},

  refreshUsage: (agentName: string) => {
    set((s) => ({
      usageLoading: { ...s.usageLoading, [agentName]: true },
      usageError: { ...s.usageError, [agentName]: false },
    }));
    fetchUsage(agentName)
      .then((data) => {
        set((s) => ({ utilization: { ...s.utilization, [agentName]: data } }));
      })
      .catch(() => {
        set((s) => ({ usageError: { ...s.usageError, [agentName]: true } }));
      })
      .finally(() => {
        set((s) => ({
          usageLoading: { ...s.usageLoading, [agentName]: false },
        }));
      });
  },
}));
