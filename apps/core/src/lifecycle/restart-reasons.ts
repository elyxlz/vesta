export interface RestartReason {
  logReason: string
  agentMessage: string
}

export interface RestartBody {
  reason: string
  agent_message: string
}

// Canonical copy for the restarts a client asks for with something specific to say. A plain manual
// restart sends no reason at all: vestad then names it itself, and can prefer the mount-grant delta
// it derives, which is more informative than anything the client could say. `reason` remains the
// wire name for operational copy so older vestad versions can still accept requests.
export const RESTART_REASONS = {
  provider: {
    logReason: "provider: configuration changed",
    agentMessage: "Your provider configuration changed.",
  },
  signOut: {
    logReason: "provider: signed out",
    agentMessage: "Your provider was signed out.",
  },
  model: {
    logReason: "provider: model changed",
    agentMessage: "Your configured model changed.",
  },
  context: {
    logReason: "provider: context window changed",
    agentMessage: "Your configured context window changed.",
  },
} as const satisfies Record<string, RestartReason>

/// The POST /restart body. Owned here so web and mobile cannot drift on the wire field names.
export function restartBody(reason: RestartReason): RestartBody {
  return { reason: reason.logReason, agent_message: reason.agentMessage }
}
