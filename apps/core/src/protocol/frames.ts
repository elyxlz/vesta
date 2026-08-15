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
// so vestad never fires the presence notification on a mere reconnect or a gateway restart.
export interface ClientContextFrame {
  type: "client_context"
  focused: boolean
  client: ClientKind
  resync: boolean
  // The device's stable installation id and the label it composes for itself. Both optional so a
  // build that does not report them is simply untracked in the device registry.
  deviceId?: string
  descriptor?: string
  // The agent whose page is open on this client, or null on the roster / a non-agent screen / a
  // blurred window. Drives the per-agent presence notification, independently of `focused`.
  viewing?: string | null
}

export type ClientKind = "web" | "mobile" | "desktop"

export type ClientFrame = ReauthFrame | ClientContextFrame

export function reauthFrame(token: string): ReauthFrame {
  return { type: "reauth", token }
}

export function clientContextFrame(
  focused: boolean,
  client: ClientKind,
  resync: boolean,
  viewing: string | null,
  device?: { id: string; descriptor: string },
): ClientContextFrame {
  const frame: ClientContextFrame = { type: "client_context", focused, client, resync, viewing }
  if (device !== undefined) {
    frame.deviceId = device.id
    frame.descriptor = device.descriptor
  }
  return frame
}

export function encodeFrame(frame: ClientFrame): string {
  return JSON.stringify(frame)
}
