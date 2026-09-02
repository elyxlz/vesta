import {
  agentOperationLabel,
  agentOrbState,
  agentStatusLabel,
  type OrbVisualState,
} from "../agent-status/agent-status";
import type {
  AgentActivityState,
  AgentOperation,
  AgentStatus,
  RateLimitedInfo,
} from "../protocol/tree";

// This client's own in-flight request, which the state tree cannot carry: it covers the gap between
// the POST and the delta reflecting it, guards against a double submit, and owns the failure
// message. Backup and restore additionally ride the roster's `operation`, which is what every other
// client and a reloaded page see.
export type AgentRequest =
  | "idle"
  | "stopping"
  | "starting"
  | "authenticating"
  | "deleting"
  | "backing-up"
  | "restoring";

export interface AgentRequestState {
  request: AgentRequest;
  error: string;
}

export const IDLE_REQUEST: AgentRequestState = Object.freeze({
  request: "idle",
  error: "",
});

export interface AgentRequests {
  get: (name: string) => AgentRequestState;
  // Holds `request` for the agent; an error lands as idle plus the message that replaces its label.
  set: (name: string, request: AgentRequest, error?: string) => void;
  clear: (name: string) => void;
  // A request only lives as long as its agent: called with the roster's names, it drops state for
  // agents that are gone, which is what ends a delete's "deleting" orb.
  reconcile: (names: Iterable<string>) => void;
  // Holds `request` while `action` runs, then clears it; a rejection lands as idle plus the
  // error's message (or `fallback`). A second submit while one is in flight is ignored.
  run: (
    name: string,
    request: AgentRequest,
    action: () => Promise<void>,
    fallback: string,
  ) => Promise<void>;
  subscribe: (listener: () => void) => () => void;
}

export function createAgentRequests(): AgentRequests {
  const states = new Map<string, AgentRequestState>();
  const listeners = new Set<() => void>();
  const notify = (): void => {
    for (const listener of listeners) listener();
  };
  const get = (name: string): AgentRequestState =>
    states.get(name) ?? IDLE_REQUEST;
  const set = (name: string, request: AgentRequest, error = ""): void => {
    states.set(name, { request, error });
    notify();
  };
  const clear = (name: string): void => {
    if (!states.has(name)) return;
    states.delete(name);
    notify();
  };
  return {
    get,
    set,
    clear,
    reconcile: (names) => {
      const alive = new Set(names);
      let changed = false;
      for (const name of [...states.keys()]) {
        if (alive.has(name)) continue;
        states.delete(name);
        changed = true;
      }
      if (changed) notify();
    },
    run: async (name, request, action, fallback) => {
      if (get(name).request !== "idle") return;
      set(name, request);
      try {
        await action();
        clear(name);
      } catch (cause: unknown) {
        const message = cause instanceof Error ? cause.message : "";
        set(name, "idle", message || fallback);
      }
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

function agentRequestLabel(request: AgentRequest): string {
  switch (request) {
    case "starting":
      return "starting...";
    case "stopping":
      return "stopping...";
    case "deleting":
      return "deleting...";
    // The words for the two vestad tracks live with the operation it publishes, so the local
    // request and the roster row cannot describe the same work differently.
    case "backing-up":
      return agentOperationLabel("backing_up");
    case "restoring":
      return agentOperationLabel("restoring");
    case "authenticating":
      return "signing in...";
    case "idle":
      return "";
  }
}

function agentRequestOrbState(
  request: Exclude<AgentRequest, "idle">,
): OrbVisualState {
  switch (request) {
    case "deleting":
      return "deleting";
    case "stopping":
    case "starting":
    case "authenticating":
    case "backing-up":
    case "restoring":
      return "busy";
  }
}

export interface AgentVisualSource {
  status: AgentStatus;
  operation: AgentOperation | null;
  booting?: boolean;
  rateLimited?: RateLimitedInfo | null;
}

interface AgentVisualStatus {
  label: string;
  orbState: OrbVisualState;
}

// The one status-to-words-and-orb derivation both apps render: this client's own request outranks
// the roster, the roster's operation outranks the container's status, then the status itself.
export function agentVisualStatus(
  agent: AgentVisualSource | null,
  request: AgentRequest,
  activityState: AgentActivityState,
): AgentVisualStatus {
  if (request !== "idle") {
    return {
      label: agentRequestLabel(request),
      orbState: agentRequestOrbState(request),
    };
  }
  if (!agent) return { label: "", orbState: "off" };
  const rateLimited = agent.rateLimited ?? null;
  return {
    label: agentStatusLabel(
      agent.status,
      activityState,
      agent.operation,
      agent.booting,
      rateLimited,
    ),
    orbState: agentOrbState(
      agent.status,
      activityState,
      agent.operation,
      agent.booting,
      rateLimited,
    ),
  };
}
