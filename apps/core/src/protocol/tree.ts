import type { NotificationEvent } from "./events"

export type AgentStatus =
  | "alive"
  | "starting"
  | "setting_up"
  | "not_authenticated"
  | "unprovisioned"
  | "restarting"
  | "rebuilding"
  | "stopped"
  | "dead"
  | "not_found"

export type AgentActivityState = "idle" | "thinking"

// Coarse, ordered stages of first-time agent creation, computed server-side and
// carried in the tree (the old build-phase polling endpoint is retired).
export type BuildPhase = "pulling" | "building" | "preparing" | "creating" | "starting"

export type ReleaseChannel = "stable" | "beta"

export interface ServiceInfo {
  port: number
  rev: number
  key?: string
}

export interface AgentInfo {
  status: AgentStatus
  activityState: AgentActivityState
  buildPhase: BuildPhase | null
  startedAt: string | null
  services: Record<string, ServiceInfo>
}

export interface GatewayLan {
  exposed: boolean
  url: string | null
}

export interface GatewayInfo {
  version: string
  channel: ReleaseChannel
  autoUpdate: boolean
  port: number
  lan: GatewayLan
  tunnelUrl: string | null
  updateAvailable: boolean
  latestVersion: string | null
  managed: boolean
}

export interface AgentNode {
  info: AgentInfo
  notifications: { pending: NotificationEvent[] }
}

export interface Tree {
  gateway: GatewayInfo
  agents: Record<string, AgentNode>
}
