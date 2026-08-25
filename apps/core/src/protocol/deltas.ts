import type { AgentInfo, DeviceInfo, GatewayInfo } from "./tree"
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

// The always-on, server-decided user-facing notification, carrying the display triple directly. Chat
// leaves the event union, so the user notification no longer embeds an event: the client routes on
// `kind` and renders `title`/`body`. Agent-injected kinds: `message` (a reply), `needs_user` (the
// agent needs the user: set up, sign in, rate limited), `task` (task activity). Gateway-minted
// kinds, `agent` empty where no agent is behind them: `gateway_updated`, `update_available`,
// `agent_status` (stopped, died, recovered), `device_connected`. `kind` stays a plain string so an
// unknown one is rendered rather than dropped, which is what keeps a new kind additive.
// Independent of any subscription; clients toast it.
export interface UserNotificationDelta {
  type: "user_notification"
  agent: string
  kind: string
  title: string
  body: string
}

export interface PresenceDelta {
  type: "presence"
  anyFocused: boolean
}

// The whole known-device list, replaced on any change (a device connecting, disconnecting, or
// registering push). Additive: an old client ignores it.
export interface DevicesDelta {
  type: "devices"
  devices: DeviceInfo[]
}

export type Delta =
  | StateDelta
  | AgentDelta
  | AgentRemovedDelta
  | NotificationsDelta
  | UserNotificationDelta
  | PresenceDelta
  | DevicesDelta
