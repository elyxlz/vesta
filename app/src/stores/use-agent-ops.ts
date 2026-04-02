import { create } from "zustand";

export type AgentOperation =
  | "idle"
  | "stopping"
  | "starting"
  | "authenticating"
  | "deleting"
  | "rebuilding"
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
  removeAgent: (name: string) => void;
  busyAgentName: () => string | null;
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
        [name]: { ...( s.states[name] ?? DEFAULT_STATE), error },
      },
    })),

  clearOp: (name) =>
    set((s) => ({
      states: { ...s.states, [name]: { operation: "idle", error: "" } },
    })),

  removeAgent: (name) =>
    set((s) => {
      const { [name]: _, ...rest } = s.states;
      return { states: rest };
    }),

  busyAgentName: () => {
    for (const [name, state] of Object.entries(get().states)) {
      if (state.operation !== "idle") return name;
    }
    return null;
  },

  withOp: async (name, op, fn, fallback) => {
    const store = get();
    if (store.getOp(name).operation !== "idle") return;
    store.setError(name, "");
    store.setOp(name, op);
    try {
      await fn();
    } catch (e: unknown) {
      const msg = (e as { message?: string })?.message || fallback;
      get().setError(name, msg);
    } finally {
      get().clearOp(name);
    }
  },
}));
