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

  removeAgent: (name) =>
    set((s) => {
      const { [name]: _, ...rest } = s.states;
      return { states: rest };
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
      const msg = (e as { message?: string })?.message || fallback;
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
    case "rebuilding":
      return "rebuilding...";
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
