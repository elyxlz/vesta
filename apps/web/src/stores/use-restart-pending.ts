import { create } from "zustand";
import { persist } from "zustand/middleware";

// Tracks agents that have a saved change which only applies after a restart. Features flag their
// agent here instead of rendering their own "restart to apply" hint, so the navbar can offer a
// single restart action. Persisted to localStorage so a page reload keeps the reminder — the change
// is already saved server-side, and a lost reminder means the user never restarts and the edit stays
// silently inert. Cleared when the agent is restarted (see SelectedAgentProvider).
interface RestartPendingState {
  pending: Record<string, boolean>;
  markPending: (agent: string) => void;
  clearPending: (agent: string) => void;
}

export const useRestartPending = create<RestartPendingState>()(
  persist(
    (set) => ({
      pending: {},
      markPending: (agent) =>
        set((state) => ({ pending: { ...state.pending, [agent]: true } })),
      clearPending: (agent) =>
        set((state) => {
          if (!state.pending[agent]) return state;
          const next = { ...state.pending };
          delete next[agent];
          return { pending: next };
        }),
    }),
    { name: "vesta-restart-pending" },
  ),
);
