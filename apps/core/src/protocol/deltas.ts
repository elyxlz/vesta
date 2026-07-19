import type { AgentInfo, GatewayInfo } from "./tree"
import type { NotificationEvent, VestaEvent } from "./events"

export interface StateDelta {
  type: "state"
  scope: "gateway"
  value: GatewayInfo
}

export interface AgentDelta {
  type: "agent"
  name: string
  info: AgentInfo
}

export interface AgentRemovedDelta {
  type: "agent_removed"
  name: string
}

export interface AppendDelta {
  type: "append"
  agent: string
  events: VestaEvent[]
}

export interface NotificationsDelta {
  type: "notifications"
  agent: string
  pending: NotificationEvent[]
}

export interface ResyncDelta {
  type: "resync"
  agent: string
}

// The always-on, server-decided notification-worthy event (chat / rate_limited), carrying the full
// event plus vestad's preview. Independent of watches; clients toast it. Additive: an old client on
// the pre-alert union simply ignored it.
export interface AlertDelta {
  type: "alert"
  agent: string
  event: VestaEvent
  preview: string
}

export type Delta =
  | StateDelta
  | AgentDelta
  | AgentRemovedDelta
  | AppendDelta
  | NotificationsDelta
  | ResyncDelta
  | AlertDelta
