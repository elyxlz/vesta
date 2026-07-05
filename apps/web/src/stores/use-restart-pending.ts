import { create } from "zustand";

// Tracks agents that have a saved change which only applies after a restart. Features flag their
// agent here instead of rendering their own "restart to apply" hint, so the navbar can offer a
// single restart action. In-memory: a page reload clears it (the change is already saved
// server-side; only the reminder is transient).
interface RestartPendingState {
  pending: Record<string, boolean>;
  markPending: (agent: string) => void;
  clearPending: (agent: string) => void;
}

export const useRestartPending = create<RestartPendingState>((set) => ({
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
}));
