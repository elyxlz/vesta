import type { AgentInfo, DeviceInfo, GatewayInfo } from "./tree";
import type { NotificationEvent } from "./events";

interface StateDelta {
  type: "state";
  scope: "gateway";
  value: GatewayInfo;
}

interface AgentDelta {
  type: "agent";
  name: string;
  info: AgentInfo;
}

interface AgentRemovedDelta {
  type: "agent_removed";
  name: string;
}

// An agent's own pending intake notifications (the files awaiting its attention), distinct from
// the user-facing `user_notification` feed below.
interface AgentNotificationsDelta {
  type: "agent_notifications";
  agent: string;
  pending: NotificationEvent[];
}

// The always-on, server-decided user-facing notification: the client routes on `kind` and renders
// `title`/`body`. Agent-injected kinds: `message` (a reply), `needs_user` (the agent needs the
// user: set up, sign in, rate limited), `task` (task activity). Gateway-minted kinds, `agent` empty
// where no agent is behind them: `gateway_updated`, `update_available`, `agent_status` (stopped,
// died, recovered), `device_connected`. `kind` stays a plain string so an unknown one is rendered
// rather than dropped, which is what keeps a new kind additive. `id` and `at` are the durable
// log's own (GET /notifications serves the same entry), so a feed joins the live edge by id.
export interface UserNotificationDelta {
  type: "user_notification";
  id: number;
  /** Unix seconds at delivery, the gateway's clock. */
  at: number;
  agent: string;
  kind: string;
  title: string;
  body: string;
}

interface PresenceDelta {
  type: "presence";
  anyFocused: boolean;
}

// The whole known-device list, replaced on any change (a device connecting, disconnecting, or
// registering push). Additive: an old client ignores it.
interface DevicesDelta {
  type: "devices";
  devices: DeviceInfo[];
}

export type Delta =
  | StateDelta
  | AgentDelta
  | AgentRemovedDelta
  | AgentNotificationsDelta
  | UserNotificationDelta
  | PresenceDelta
  | DevicesDelta;
