import { create } from "zustand";
import { persist } from "zustand/middleware";

// Tracks agents that have a saved change which only applies after a restart. Features flag their
// agent here (each under its own reason key) instead of rendering their own "restart to apply"
// hint, so the navbar can offer a single restart action. Per-reason tracking lets a feature
// withdraw its own flag when its setting is toggled back to the applied value, without wiping
// another feature's legitimate reminder. Persisted to localStorage so a page reload keeps the
// reminder — the change is already saved server-side, and a lost reminder means the user never
// restarts and the edit stays silently inert. Cleared when the agent is restarted (see
// SelectedAgentProvider).
interface RestartPendingState {
  pending: Record<string, string[]>;
  markPending: (agent: string, reason: string) => void;
  clearReason: (agent: string, reason: string) => void;
  clearPending: (agent: string) => void;
}

export const useRestartPending = create<RestartPendingState>()(
  persist(
    (set) => ({
      pending: {},
      markPending: (agent, reason) =>
        set((state) => {
          const reasons = state.pending[agent] ?? [];
          if (reasons.includes(reason)) return state;
          return {
            pending: { ...state.pending, [agent]: [...reasons, reason] },
          };
        }),
      clearReason: (agent, reason) =>
        set((state) => {
          const reasons = state.pending[agent];
          if (!reasons?.includes(reason)) return state;
          const remaining = reasons.filter((r) => r !== reason);
          const next = { ...state.pending };
          if (remaining.length === 0) delete next[agent];
          else next[agent] = remaining;
          return { pending: next };
        }),
      clearPending: (agent) =>
        set((state) => {
          if (!state.pending[agent]) return state;
          const next = { ...state.pending };
          delete next[agent];
          return { pending: next };
        }),
    }),
    {
      name: "vesta-restart-pending",
      version: 1,
      // v0 stored Record<string, boolean>; carry the reminder over under a generic reason.
      migrate: (persisted: unknown) => {
        const state = persisted as { pending?: Record<string, unknown> };
        const pending: Record<string, string[]> = {};
        for (const [agent, value] of Object.entries(state.pending ?? {})) {
          if (value === true) pending[agent] = ["settings"];
          else if (Array.isArray(value)) pending[agent] = value as string[];
        }
        return { pending };
      },
    },
  ),
);
