import type { AgentActivityState, AgentOperation, AgentStatus } from "../protocol/tree"

// What an AgentStatus means for the user, which is what every surface actually branches on: is the
// agent working, is it waiting on me, is it down. The only exhaustive switch over AgentStatus in the
// codebase, so adding a status is a compile error here instead of a silent "healthy" at ten sites.
export type AgentStatusKind = "alive" | "working" | "needs-user" | "down"

export function agentStatusKind(status: AgentStatus): AgentStatusKind {
  switch (status) {
    case "alive":
      return "alive"
    case "starting":
    case "setting_up":
    case "restarting":
    case "rebuilding":
      return "working"
    case "not_authenticated":
    case "unprovisioned":
      return "needs-user"
    case "stopped":
    case "dead":
    case "not_found":
      return "down"
  }
}

// Up and answering, but unable to work until the user signs in or finishes setting it up. Nothing
// resolves this on its own.
export function agentNeedsUser(status: AgentStatus): boolean {
  return agentStatusKind(status) === "needs-user"
}

// Whether the agent's own server answers, which is what a chat socket or a start poll waits for. An
// agent waiting on the user is still connectable: history loads, the composer stays disabled.
export function agentIsConnectable(status: AgentStatus): boolean {
  const kind = agentStatusKind(status)
  return kind === "alive" || kind === "needs-user"
}

// No container to reach and nothing in flight that will produce one, so a poller waiting for this
// agent to come up should give up rather than time out.
export function agentIsDown(status: AgentStatus): boolean {
  return agentStatusKind(status) === "down"
}

// The visual buckets the orb renders. `deleting` has no matching AgentStatus: it is a client-side
// operation, mapped by the surface that tracks operations.
export type OrbVisualState = "alive" | "thinking" | "busy" | "off" | "deleting"

// The one status-to-orb mapping both surfaces read, so a new AgentStatus is a compile error in
// agentStatusKind rather than a silent `off` on web and mobile independently.
export function agentOrbState(
  status: AgentStatus,
  activityState: AgentActivityState,
  operation: AgentOperation | null = null,
  booting = false,
): OrbVisualState {
  // A running operation outranks the container's own status: a backup pauses the container, so the
  // status alone would read as a plainly stopped agent that the user has to restart.
  if (operation !== null) return "busy"
  // An alive agent still in its boot turns renders as the boot it is finishing, not as thinking.
  if (booting && status === "alive") return "busy"
  switch (agentStatusKind(status)) {
    case "alive":
      return activityState === "thinking" ? "thinking" : "alive"
    case "working":
      return "busy"
    case "needs-user":
    case "down":
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
  booting = false,
): string {
  if (operation !== null) return agentOperationLabel(operation)
  // The boot reads as one continuous "waking up...": container start through the last boot turn.
  if (booting && status === "alive") return "waking up..."
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
