import { create } from "zustand";
import { errorMessage } from "@/lib/utils";

export type AgentOperation =
  | "idle"
  | "stopping"
  | "starting"
  | "authenticating"
  | "deleting"
  | "backing-up"
  | "restoring";

interface AgentOpState {
  operation: AgentOperation;
  error: string;
}

interface AgentOpsStore {
  states: Record<string, AgentOpState>;
  getOp: (name: string) => AgentOpState;
  setOp: (name: string, operation: AgentOperation, error?: string) => void;
  setError: (name: string, error: string) => void;
  clearOp: (name: string) => void;
  reconcile: (agents: { name: string }[]) => void;
  withOp: (
    name: string,
    op: AgentOperation,
    fn: () => Promise<void>,
    fallback: string,
  ) => Promise<void>;
}

const DEFAULT_STATE: AgentOpState = { operation: "idle", error: "" };

export const useAgentOps = create<AgentOpsStore>((set, get) => ({
  states: {},

  getOp: (name) => get().states[name] ?? DEFAULT_STATE,

  setOp: (name, operation, error = "") =>
    set((s) => ({
      states: { ...s.states, [name]: { operation, error } },
    })),

  setError: (name, error) =>
    set((s) => ({
      states: {
        ...s.states,
        [name]: { ...(s.states[name] ?? DEFAULT_STATE), error },
      },
    })),

  clearOp: (name) =>
    set((s) => ({
      states: { ...s.states, [name]: { operation: "idle", error: "" } },
    })),

  // An op only lives as long as its agent: on each gateway agents push, drop op
  // state for agents that are gone. This is what ends a delete's "deleting" orb,
  // so the card never flashes back to idle while the deleted agent lingers.
  reconcile: (agents) =>
    set((s) => {
      const alive = new Set(agents.map((a) => a.name));
      const stale = Object.keys(s.states).filter((n) => !alive.has(n));
      if (stale.length === 0) return s;
      const states = { ...s.states };
      for (const name of stale) delete states[name];
      return { states };
    }),

  withOp: async (name, op, fn, fallback) => {
    const store = get();
    if (store.getOp(name).operation !== "idle") return;
    store.setError(name, "");
    store.setOp(name, op);
    try {
      await fn();
      get().clearOp(name);
    } catch (e: unknown) {
      const msg = errorMessage(e, fallback);
      set((s) => ({
        states: { ...s.states, [name]: { operation: "idle", error: msg } },
      }));
    }
  },
}));

export function getOpLabel(op: AgentOperation): string {
  switch (op) {
    case "starting":
      return "starting...";
    case "stopping":
      return "stopping...";
    case "deleting":
      return "deleting...";
    case "backing-up":
      return "backing up...";
    case "restoring":
      return "restoring...";
    case "authenticating":
      return "signing in...";
    default:
      return "";
  }
}
