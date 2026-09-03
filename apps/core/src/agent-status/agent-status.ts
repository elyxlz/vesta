import type {
  AgentActivityState,
  AgentOperation,
  AgentStatus,
  RateLimitedInfo,
} from "../protocol/tree";

// What an AgentStatus means for the user, which is what every surface actually branches on: is the
// agent working, is it waiting on me, is it down. The only exhaustive switch over AgentStatus in the
// codebase, so adding a status is a compile error here instead of a silent "healthy" at ten sites.
export type AgentStatusKind = "alive" | "working" | "needs-user" | "down";

export function agentStatusKind(status: AgentStatus): AgentStatusKind {
  switch (status) {
    case "alive":
      return "alive";
    case "starting":
    case "setting_up":
    case "restarting":
    case "rebuilding":
      return "working";
    case "not_authenticated":
    case "unprovisioned":
      return "needs-user";
    case "stopped":
    case "dead":
    case "not_found":
      return "down";
  }
}

// Up and answering, but unable to work until the user signs in or finishes setting it up. Nothing
// resolves this on its own.
export function agentNeedsUser(status: AgentStatus): boolean {
  return agentStatusKind(status) === "needs-user";
}

// Whether the agent's own server answers, which is what a chat socket or a start poll waits for. An
// agent waiting on the user is still connectable: history loads, the composer stays disabled.
export function agentIsConnectable(status: AgentStatus): boolean {
  const kind = agentStatusKind(status);
  return kind === "alive" || kind === "needs-user";
}

// No container to reach and nothing in flight that will produce one, so a poller waiting for this
// agent to come up should give up rather than time out.
export function agentIsDown(status: AgentStatus): boolean {
  return agentStatusKind(status) === "down";
}

// The visual buckets the orb renders. `deleting` has no matching AgentStatus: it is a client-side
// operation, mapped by the surface that tracks operations. `limited` is the rate-limited overlay:
// alive but unable to work until the provider's window resets. `attention` is a state only the
// user can resolve (sign in, set up), kept apart from `off` so it never reads as merely stopped.
export type OrbVisualState =
  "alive" | "thinking" | "busy" | "limited" | "attention" | "off" | "deleting";

// The one status-to-orb mapping both surfaces read, so a new AgentStatus is a compile error in
// agentStatusKind rather than a silent `off` on web and mobile independently.
export function agentOrbState(
  status: AgentStatus,
  activityState: AgentActivityState,
  operation: AgentOperation | null = null,
  booting = false,
  rateLimited: RateLimitedInfo | null = null,
): OrbVisualState {
  // A running operation outranks the container's own status: a backup pauses the container, so the
  // status alone would read as a plainly stopped agent that the user has to restart.
  if (operation !== null) return "busy";
  // An alive agent still in its boot turns renders as the boot it is finishing, not as thinking.
  if (booting && status === "alive") return "busy";
  // A binding rate limit outranks the activity: the CLI may still be retrying ("thinking"), but no
  // work can land, and a green orb here is the lie this state exists to correct.
  if (rateLimited != null && status === "alive") return "limited";
  switch (agentStatusKind(status)) {
    case "alive":
      return activityState === "thinking" ? "thinking" : "alive";
    case "working":
      return "busy";
    case "needs-user":
      return "attention";
    case "down":
      return "off";
  }
}

const LIVE_STATES: ReadonlySet<OrbVisualState> = new Set([
  "alive",
  "thinking",
  "busy",
]);

// Whether the orb animates. A still orb is what tells the user the state will not resolve itself.
export function orbIsLive(state: OrbVisualState): boolean {
  return LIVE_STATES.has(state);
}

// Coarse relative countdown to a rate-limit reset (unix seconds); minutes/hours/days is
// plenty of precision for "come back later" copy.
export function formatResetTime(resetsAt: number): string {
  const minutes = Math.round((resetsAt * 1000 - Date.now()) / 60_000);
  if (minutes <= 1) return "in a minute";
  if (minutes < 60) return `in ${String(minutes)}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `in ${String(hours)}h`;
  return `in ${String(Math.round(hours / 24))}d`;
}

// The words for a status, shared so web's orb line and mobile's badge cannot drift apart. The two
// waiting states name the user as the actor, matching the notification and push copy for them.
export function agentStatusLabel(
  status: AgentStatus,
  activityState: AgentActivityState,
  operation: AgentOperation | null = null,
  booting = false,
  rateLimited: RateLimitedInfo | null = null,
): string {
  if (operation !== null) return agentOperationLabel(operation);
  // The boot reads as one continuous "waking up...": container start through the last boot turn.
  if (booting && status === "alive") return "waking up...";
  if (rateLimited != null && status === "alive") {
    return rateLimited.resetsAt != null
      ? `rate limited, back ${formatResetTime(rateLimited.resetsAt)}`
      : "rate limited";
  }
  switch (status) {
    case "alive":
      return activityState === "thinking" ? "thinking" : "alive";
    case "starting":
      return "waking up...";
    case "setting_up":
      return "setting up...";
    case "not_authenticated":
      return "needs you to sign in";
    case "unprovisioned":
      return "needs to be set up";
    case "restarting":
      return "restarting...";
    case "rebuilding":
      return "updating...";
    case "stopped":
      return "stopped";
    case "dead":
      return "broken";
    case "not_found":
      return "unavailable";
  }
}

export function agentOperationLabel(operation: AgentOperation): string {
  switch (operation) {
    case "backing_up":
      return "backing up...";
    case "restoring":
      return "restoring...";
  }
}
