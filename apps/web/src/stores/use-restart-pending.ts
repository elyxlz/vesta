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
// The reason vocabulary is the withdraw contract: clearReason only matches an identical key,
// so the store owns the spelling. "settings" only labels flags migrated from the un-keyed v0 store.
export type RestartReason = "host-access" | "files" | "preempt-mode" | "settings";

interface RestartPendingState {
  pending: Record<string, RestartReason[]>;
  markPending: (agent: string, reason: RestartReason) => void;
  clearReason: (agent: string, reason: RestartReason) => void;
  clearPending: (agent: string) => void;
}

function without(
  pending: Record<string, RestartReason[]>,
  agent: string,
): Record<string, RestartReason[]> {
  const next = { ...pending };
  delete next[agent];
  return next;
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
          if (remaining.length === 0)
            return { pending: without(state.pending, agent) };
          return { pending: { ...state.pending, [agent]: remaining } };
        }),
      clearPending: (agent) =>
        set((state) => {
          if (!state.pending[agent]) return state;
          return { pending: without(state.pending, agent) };
        }),
    }),
    {
      name: "vesta-restart-pending",
      version: 1,
      // v0 stored Record<string, boolean>; carry the reminder over under a generic reason.
      migrate: (persisted: unknown) => {
        const state = persisted as { pending?: Record<string, unknown> };
        const pending: Record<string, RestartReason[]> = {};
        for (const [agent, value] of Object.entries(state.pending ?? {})) {
          if (value === true) pending[agent] = ["settings"];
        }
        return { pending };
      },
    },
  ),
);
