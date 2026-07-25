// Names for the restarts a client asks for. vestad owns the copy each token resolves to
// (vestad/src/lifecycle.rs), so every word the agent reads has one author; the token list itself is
// pinned against vestad's by restart-reasons.test.ts.
//
// A plain manual restart sends no token at all: vestad then names it itself, and can prefer the
// mount-grant delta it derives, which is more informative than anything the client could say.
export const RESTART_REASONS = {
  provider: "provider.configured",
  signOut: "provider.signed-out",
  model: "provider.model",
  context: "provider.context",
} as const

export type RestartReason = (typeof RESTART_REASONS)[keyof typeof RESTART_REASONS]

export interface RestartBody {
  reason_token: RestartReason
}

/// The POST /restart body. Owned here so web and mobile cannot drift on the wire field name.
export function restartBody(reason: RestartReason): RestartBody {
  return { reason_token: reason }
}
