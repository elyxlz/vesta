// ── Per-agent operation state ────────────────────────────────────

export type AgentOperation = "idle" | "stopping" | "starting" | "authenticating" | "deleting" | "rebuilding" | "backing-up" | "restoring";

type AgentOpState = {
  operation: AgentOperation;
  error: string;
};

let agentStates = $state<Record<string, AgentOpState>>({});

export function getAgentOp(name: string): AgentOpState {
  return agentStates[name] ?? { operation: "idle", error: "" };
}

function setAgentOp(name: string, operation: AgentOperation, error = "") {
  agentStates[name] = { operation, error };
}

export function setAgentError(name: string, error: string) {
  const current = agentStates[name];
  if (current) {
    agentStates[name] = { ...current, error };
  } else {
    agentStates[name] = { operation: "idle", error };
  }
}

function clearAgentOp(name: string) {
  agentStates[name] = { operation: "idle", error: "" };
}

export function removeAgentState(name: string) {
  const { [name]: _, ...rest } = agentStates;
  agentStates = rest;
}

export function busyAgentName(): string | null {
  for (const [name, state] of Object.entries(agentStates)) {
    if (state.operation !== "idle") return name;
  }
  return null;
}

export async function withAgentOp(name: string, op: AgentOperation, fn: () => Promise<void>, fallback: string): Promise<void> {
  if (getAgentOp(name).operation !== "idle") return;
  setAgentError(name, "");
  setAgentOp(name, op);
  try {
    await fn();
  } catch (e: unknown) {
    setAgentError(name, (e as { message?: string })?.message || fallback);
  } finally {
    clearAgentOp(name);
  }
}
