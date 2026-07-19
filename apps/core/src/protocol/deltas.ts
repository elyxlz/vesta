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

export type Delta =
  StateDelta | AgentDelta | AgentRemovedDelta | AppendDelta | NotificationsDelta | ResyncDelta
