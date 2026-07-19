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

export interface WatchFrame {
  type: "watch"
  agent: string
}

export interface UnwatchFrame {
  type: "unwatch"
  agent: string
}

export interface ReauthFrame {
  type: "reauth"
  token: string
}

export type ClientFrame = WatchFrame | UnwatchFrame | ReauthFrame

export function watchFrame(agent: string): WatchFrame {
  return { type: "watch", agent }
}

export function unwatchFrame(agent: string): UnwatchFrame {
  return { type: "unwatch", agent }
}

export function reauthFrame(token: string): ReauthFrame {
  return { type: "reauth", token }
}

export function encodeFrame(frame: ClientFrame): string {
  return JSON.stringify(frame)
}
