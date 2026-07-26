import type { Tree } from "./tree"

// The served compatibility window: the gateway's own release `version` and the oldest client
// release it still accepts (`minSupported`, wire `min_supported`). A client compares its own
// build version to decide app_behind / gateway_behind / proceed (see transport/socket.ts).
export interface HelloFrame {
  type: "hello"
  version: string
  minSupported: string
}

export interface SnapshotFrame {
  type: "snapshot"
  tree: Tree
}

export interface ReauthFrame {
  type: "reauth"
  token: string
}

export interface ClientContextFrame {
  type: "client_context"
  focused: boolean
  active_agent: string | null
}

export type ClientFrame = ReauthFrame | ClientContextFrame

export function reauthFrame(token: string): ReauthFrame {
  return { type: "reauth", token }
}

export function clientContextFrame(focused: boolean, activeAgent: string | null): ClientContextFrame {
  return { type: "client_context", focused, active_agent: activeAgent }
}

export function encodeFrame(frame: ClientFrame): string {
  return JSON.stringify(frame)
}
