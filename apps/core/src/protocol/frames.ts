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

// `resync` is true when the socket replays its cached context on reconnect (not a fresh user focus),
// so vestad never fires the return-to-focus notification on a mere reconnect or a gateway restart.
export interface ClientContextFrame {
  type: "client_context"
  focused: boolean
  resync: boolean
}

export type ClientFrame = ReauthFrame | ClientContextFrame

export function reauthFrame(token: string): ReauthFrame {
  return { type: "reauth", token }
}

export function clientContextFrame(
  focused: boolean,
  resync: boolean,
): ClientContextFrame {
  return { type: "client_context", focused, resync }
}

export function encodeFrame(frame: ClientFrame): string {
  return JSON.stringify(frame)
}
