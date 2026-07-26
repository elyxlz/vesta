import type { AgentActivityState, AgentOperation, AgentStatus } from "../protocol/tree"

// The visual buckets the orb renders. `deleting` has no matching AgentStatus: it is a client-side
// operation, mapped by the surface that tracks operations.
export type OrbVisualState = "alive" | "thinking" | "busy" | "off" | "deleting"

// The one status-to-orb mapping both surfaces read, so a new AgentStatus is a compile error here
// rather than a silent `off` on web and mobile independently.
export function agentOrbState(
  status: AgentStatus,
  activityState: AgentActivityState,
  operation: AgentOperation | null = null,
): OrbVisualState {
  // A running operation outranks the container's own status: a backup pauses the container, so the
  // status alone would read as a plainly stopped agent that the user has to restart.
  if (operation !== null) return "busy"
  switch (status) {
    case "alive":
      return activityState === "thinking" ? "thinking" : "alive"
    case "starting":
    case "setting_up":
    case "restarting":
    case "rebuilding":
      return "busy"
    case "not_authenticated":
    case "unprovisioned":
    case "stopped":
    case "dead":
    case "not_found":
      return "off"
  }
}

const LIVE_STATES: ReadonlySet<OrbVisualState> = new Set(["alive", "thinking", "busy"])

// Whether the orb animates. A still orb is what tells the user the state will not resolve itself.
export function orbIsLive(state: OrbVisualState): boolean {
  return LIVE_STATES.has(state)
}

// The words for a status, shared so web's orb line and mobile's badge cannot drift apart. The two
// waiting states name the user as the actor, matching the notification and push copy for them.
export function agentStatusLabel(
  status: AgentStatus,
  activityState: AgentActivityState,
  operation: AgentOperation | null = null,
): string {
  if (operation !== null) return agentOperationLabel(operation)
  switch (status) {
    case "alive":
      return activityState === "thinking" ? "thinking" : "alive"
    case "starting":
      return "waking up..."
    case "setting_up":
      return "setting up..."
    case "not_authenticated":
      return "needs you to sign in"
    case "unprovisioned":
      return "needs to be set up"
    case "restarting":
      return "restarting..."
    case "rebuilding":
      return "updating..."
    case "stopped":
      return "stopped"
    case "dead":
      return "broken"
    case "not_found":
      return "unavailable"
  }
}

export function agentOperationLabel(operation: AgentOperation): string {
  switch (operation) {
    case "backing_up":
      return "backing up..."
    case "restoring":
      return "restoring..."
  }
}
