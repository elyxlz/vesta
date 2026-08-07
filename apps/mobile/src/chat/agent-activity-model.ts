import type { AgentActivityState, Tree } from "@vesta/core";

export interface AgentActivitySnapshot {
  state: AgentActivityState;
  ready: boolean;
}

export function selectAgentActivitySnapshot(
  tree: Tree | null,
  active: boolean,
  name: string,
): AgentActivitySnapshot {
  if (tree === null) return { state: "idle", ready: false };
  return {
    state:
      active && name
        ? (tree.agents[name]?.info.activityState ?? "idle")
        : "idle",
    ready: true,
  };
}

export function agentActivitySnapshotsEqual(
  left: AgentActivitySnapshot,
  right: AgentActivitySnapshot,
): boolean {
  return left.state === right.state && left.ready === right.ready;
}

export function servedAgentActivity(
  snapshot: AgentActivitySnapshot,
  heldState: AgentActivityState | undefined,
): AgentActivityState {
  return snapshot.ready ? snapshot.state : (heldState ?? snapshot.state);
}
