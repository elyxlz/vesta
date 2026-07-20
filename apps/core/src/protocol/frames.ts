import type { Tree } from "./tree"

export interface HelloFrame {
  type: "hello"
  version: string
  protocol: number
  floor: number
}

export interface SnapshotFrame {
  type: "snapshot"
  tree: Tree
}

export interface ReauthFrame {
  type: "reauth"
  token: string
}

export type ClientFrame = ReauthFrame

export function reauthFrame(token: string): ReauthFrame {
  return { type: "reauth", token }
}

export function encodeFrame(frame: ClientFrame): string {
  return JSON.stringify(frame)
}
