import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { AgentInfo } from "@/lib/types";

// Tracks agents that have a saved change which only applies after a restart. Features flag their
// agent here (each under its own reason key) instead of rendering their own "restart to apply"
// hint, so the navbar can offer a single restart action. Per-reason tracking lets a feature
// withdraw its own flag when its setting is toggled back to the applied value, without wiping
// another feature's legitimate reminder. Persisted to localStorage so a page reload keeps the
// reminder — the change is already saved server-side, and a lost reminder means the user never
// restarts and the edit stays silently inert.
// The flag is cleared by observing the agent actually restart: markPending stamps the agent's boot
// time (`since`), and reconcile drops the flag once a different boot time is seen (see reconcile), so
// a restart by any path — the navbar button, the CLI, another tab/device, a crash, the nightly
// dreamer — clears it, not only a restart this browser triggered. The exception is host-access: a
// new bind mount needs a container *recreate*, which a boot-time change can't distinguish from a
// plain/crash restart that reused the old mounts, so reconcile leaves those reasons for the app
// restart button's clear (which does recreate) rather than risk dropping a still-inert grant.

// ALL_REASONS is the single source for the reason vocabulary: it's the withdraw contract
// (clearReason matches an identical key, so the store owns the spelling) and the runtime allowlist
// migrate narrows untrusted persisted data against; RestartReason derives from it so the two never
// drift. "settings" only labels flags migrated from the un-keyed v0 store.
const ALL_REASONS = ["host-access", "files", "settings"] as const;
export type RestartReason = (typeof ALL_REASONS)[number];

// Reasons reconcile must not clear on a boot-time change — they need a container recreate, not a
// mere restart (see the header). host-access qualifies: bind mounts are fixed at container create.
const RECREATE_ONLY_REASONS: readonly RestartReason[] = ["host-access"];

// `since` is the agent's container start time (AgentInfo.startedAt) captured when the change was
// saved; null when it wasn't known. Only the restart-applied reasons consult it — host-access
// threads it too (so a later mixed entry has a baseline) but clears via the button regardless.
interface PendingEntry {
  reasons: RestartReason[];
  since: string | null;
}

// A restart observation: the subset of AgentInfo reconcile needs, kept coupled to the wire type.
type AgentBoot = Pick<AgentInfo, "name" | "startedAt">;

interface RestartPendingState {
  pending: Record<string, PendingEntry>;
  markPending: (
    agent: string,
    reason: RestartReason,
    startedAt: string | undefined,
  ) => void;
  clearReason: (agent: string, reason: RestartReason) => void;
  clearPending: (agent: string) => void;
  reconcile: (agents: AgentBoot[]) => void;
}

function without(
  pending: Record<string, PendingEntry>,
  agent: string,
): Record<string, PendingEntry> {
  const next = { ...pending };
  delete next[agent];
  return next;
}

export function migrateRestartPending(
  persisted: unknown,
  version: number,
): { pending: Record<string, PendingEntry> } {
  const state = persisted as { pending?: Record<string, unknown> };
  const pending: Record<string, PendingEntry> = {};
  for (const [agent, value] of Object.entries(state.pending ?? {})) {
    if (version === 0) {
      // v0 stored Record<string, boolean>; carry the reminder over under a generic reason.
      if (value === true)
        pending[agent] = { reasons: ["settings"], since: null };
    } else if (Array.isArray(value)) {
      // v1 stored Record<string, RestartReason[]>; no boot time was captured back then. Narrow
      // rather than trust the persisted shape — drop anything that isn't a known reason.
      const reasons = value.filter(
        (r): r is RestartReason =>
          typeof r === "string" &&
          (ALL_REASONS as readonly string[]).includes(r),
      );
      if (reasons.length) pending[agent] = { reasons, since: null };
    }
  }
  return { pending };
}

export const useRestartPending = create<RestartPendingState>()(
  persist(
    (set) => ({
      pending: {},
      markPending: (agent, reason, startedAt) =>
        set((state) => {
          const entry = state.pending[agent];
          if (entry?.reasons.includes(reason)) return state;
          // Advance the baseline to this save's boot when it's known, else keep the prior one — a
          // transient undefined (agent not yet loaded) must not erase a good baseline down to null.
          const reasons = entry ? [...entry.reasons, reason] : [reason];
          return {
            pending: {
              ...state.pending,
              [agent]: { reasons, since: startedAt ?? entry?.since ?? null },
            },
          };
        }),
      clearReason: (agent, reason) =>
        set((state) => {
          const entry = state.pending[agent];
          if (!entry?.reasons.includes(reason)) return state;
          const remaining = entry.reasons.filter((r) => r !== reason);
          if (remaining.length === 0)
            return { pending: without(state.pending, agent) };
          return {
            pending: {
              ...state.pending,
              [agent]: { ...entry, reasons: remaining },
            },
          };
        }),
      clearPending: (agent) =>
        set((state) => {
          if (!state.pending[agent]) return state;
          return { pending: without(state.pending, agent) };
        }),
      // Retire reasons once the agent is observed running a different container start than the one
      // the change was saved against — the restart applied them, whoever triggered it. Recreate-only
      // reasons survive (see RECREATE_ONLY_REASONS). A flag whose boot time is unknown (migrated)
      // pins the current boot as its baseline on first sighting, so it clears on the next restart
      // rather than lingering forever.
      reconcile: (agents) =>
        set((state) => {
          let pending = state.pending;
          for (const { name, startedAt } of agents) {
            const entry = pending[name];
            if (!entry || !startedAt) continue;
            if (entry.since === null) {
              pending = { ...pending, [name]: { ...entry, since: startedAt } };
            } else if (startedAt !== entry.since) {
              const survivors = entry.reasons.filter((r) =>
                RECREATE_ONLY_REASONS.includes(r),
              );
              pending =
                survivors.length === 0
                  ? without(pending, name)
                  : {
                      ...pending,
                      [name]: { reasons: survivors, since: startedAt },
                    };
            }
          }
          return pending === state.pending ? state : { pending };
        }),
    }),
    {
      name: "vesta-restart-pending",
      version: 2,
      migrate: migrateRestartPending,
    },
  ),
);
