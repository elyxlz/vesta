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
  buildPhase: BuildPhase | null
  operation: AgentOperation | null
  startedAt: string | null
  services: Record<string, ServiceInfo>
}

export interface GatewayLan {
  exposed: boolean
  url: string | null
}

// The steps a gateway operation moves through. Terminal success is absent by design: a finished
// operation clears the slot and the new version shows up on the gateway node itself.
export type GatewayOperationPhase = "snapshotting" | "applying" | "restarting" | "failed"

// What the gateway is doing to itself. A restart is an operation too, reported on the one phase an
// update also ends on, so it renders on the screen the update already has.
export type GatewayOperationKind = "update" | "restart"

// The gateway-wide operation in flight. Like an agent's `operation`, it outlives the request that
// started it, so every client sees the same progress rather than only the one that asked. The
// progress fields carry values only while snapshotting, `error` only on a failure, and
// `targetVersion` only for an update, a restart having no release to name.
export interface GatewayOperation {
  kind: GatewayOperationKind
  phase: GatewayOperationPhase
  agent: string | null
  done: number | null
  total: number | null
  targetVersion: string | null
  warnings: string[]
  error: string | null
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
  operation: GatewayOperation | null
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
