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

export type ModelAccess =
  | { state: "available"; reason: null; until: null; window: null }
  | {
      state: "cooling_down"
      reason: "rate_limit"
      until: number
      window: string | null
    }

// A long-running operation vestad is running against an existing agent. Distinct from AgentStatus,
// which describes the container: both of these run against an agent whose container state barely
// changes, so only the roster reveals them, and to every client rather than just the initiator.
export type AgentOperation = "backing_up" | "restoring"

// Coarse, ordered stages of first-time agent creation, computed server-side and
// carried in the tree (the old build-phase polling endpoint is retired).
export type BuildPhase = "pulling" | "building" | "preparing" | "creating" | "starting"

export type ReleaseChannel = "stable" | "beta"

export interface ServiceInfo {
  port: number
  rev: number
}

export interface AgentInfo {
  status: AgentStatus
  activityState: AgentActivityState
  modelAccess?: ModelAccess
  buildPhase: BuildPhase | null
  operation: AgentOperation | null
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

// The kind vestad reports for a known device. Unlike the client-reported ClientKind (frames.ts),
// this can be "unknown" for a device that connected without identifying its surface.
export type DeviceKind = "web" | "mobile" | "desktop" | "unknown"

// One device in the gateway-global registry: identity plus whether it currently holds a live /sync
// connection, or when it last did. The push token is never on the wire; `pushEnabled` is the only
// push signal. `descriptor` is null until a device connects and names itself. `location` is a coarse
// "City, Country" the gateway resolves from the connection, null until resolved.
export interface DeviceInfo {
  id: string
  kind: DeviceKind
  descriptor: string | null
  present: boolean
  lastSeen: string
  pushEnabled: boolean
  location: string | null
}

export interface Tree {
  gateway: GatewayInfo
  agents: Record<string, AgentNode>
  devices: DeviceInfo[]
}
