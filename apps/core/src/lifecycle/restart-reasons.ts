// Canonical restart reasons sent by both first-party clients. The gateway still accepts a
// free-form reason for external callers and supplies its own fallback for bodyless requests.
export const RESTART_REASONS = {
  manual: "manual: restart requested",
  provider: "provider: provider configuration changed",
  signOut: "provider: signed out",
  model: "provider: model changed",
  context: "provider: context window changed",
} as const
