import type { AgentInfo, GatewayInfo } from "./tree"
import type { NotificationEvent } from "./events"

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

export interface NotificationsDelta {
  type: "notifications"
  agent: string
  pending: NotificationEvent[]
}

// The always-on, server-decided user-facing alert (a new chat reply or a rate limit), carrying the
// display triple directly. Chat leaves the event union, so the alert no longer embeds an event: the
// client routes on `kind` and renders `title`/`body`. Independent of any subscription; clients toast
// it. Additive: an old client on the pre-alert union simply ignores it.
export interface AlertDelta {
  type: "alert"
  agent: string
  kind: string
  title: string
  body: string
}

export type Delta = StateDelta | AgentDelta | AgentRemovedDelta | NotificationsDelta | AlertDelta
