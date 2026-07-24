export interface RestartReason {
  logReason: string
  agentMessage: string
}

// Canonical restart copy sent by both first-party clients. `reason` remains the wire name for
// operational copy so older vestad versions can still accept requests and ignore agent_message.
export const RESTART_REASONS = {
  manual: {
    logReason: "manual: restart requested",
    agentMessage: "You were restarted manually.",
  },
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
