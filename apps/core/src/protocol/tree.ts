import type { NotificationEvent } from "./events";

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
  | "not_found";

export type AgentActivityState = "idle" | "thinking";

// A long-running operation vestad is running against an existing agent. Distinct from AgentStatus,
// which describes the container: both of these run against an agent whose container state barely
// changes, so only the roster reveals them, and to every client rather than just the initiator.
export type AgentOperation = "backing_up" | "restoring";

// Coarse, ordered stages of first-time agent creation, computed server-side and
// carried in the tree (the old build-phase polling endpoint is retired).
export type BuildPhase =
  "pulling" | "building" | "preparing" | "creating" | "starting";

export type ReleaseChannel = "stable" | "beta";

export interface ServiceInfo {
  port: number;
  rev: number;
  // Registered public: served with no gateway credential.
  public: boolean;
}

// The rate-limit window binding an alive agent: the agent serves, but its provider rejects work
// until the window resets. `window` names the provider's limit window ("five_hour", "seven_day",
// ...); `resetsAt` is unix seconds. Both null when the rejection carried no classification.
export interface RateLimitedInfo {
  window: string | null;
  resetsAt: number | null;
}

export interface AgentInfo {
  status: AgentStatus;
  activityState: AgentActivityState;
  buildPhase: BuildPhase | null;
  operation: AgentOperation | null;
  // An alive agent still working through its boot turns (migrations, sync, greeting): its API
  // serves and chat queues durably, but surfaces label it as still waking up. Absent on older
  // gateways, so readers treat undefined as false.
  booting?: boolean;
  // Present exactly while a rate limit binds the agent; absent on older gateways and while clear.
  rateLimited?: RateLimitedInfo | null;
  startedAt: string | null;
  services: Record<string, ServiceInfo>;
}

interface GatewayLan {
  exposed: boolean;
  url: string | null;
}

// The steps a gateway operation moves through. Terminal success is absent by design: a finished
// operation clears the slot and the new version shows up on the gateway node itself.
export type GatewayOperationPhase =
  "snapshotting" | "applying" | "restarting" | "failed";

// What the gateway is doing to itself. A restart is an operation too, reported on the one phase an
// update also ends on, so it renders on the screen the update already has.
export type GatewayOperationKind = "update" | "restart";

// The gateway-wide operation in flight. Like an agent's `operation`, it outlives the request that
// started it, so every client sees the same progress rather than only the one that asked. The
// progress fields carry values only while snapshotting, `error` only on a failure, and
// `targetVersion` only for an update, a restart having no release to name.
export interface GatewayOperation {
  kind: GatewayOperationKind;
  phase: GatewayOperationPhase;
  agent: string | null;
  done: number | null;
  total: number | null;
  targetVersion: string | null;
  warnings: string[];
  error: string | null;
}

export interface GatewayInfo {
  version: string;
  channel: ReleaseChannel;
  autoUpdate: boolean;
  port: number;
  lan: GatewayLan;
  tunnelUrl: string | null;
  updateAvailable: boolean;
  latestVersion: string | null;
  managed: boolean;
  operation: GatewayOperation | null;
  // The user-notification feed's synced seen watermark (unix seconds of the user's last catch-up
  // on any device, 0 before the first) and the newest logged entry's stamp (null on an empty
  // log). Unseen is derived: an entry is unseen while its `at` is above the watermark. Absent on
  // older gateways, so readers treat undefined as 0 / null.
  userNotificationsSeenAt?: number;
  lastUserNotificationAt?: number | null;
}

export interface AgentNode {
  info: AgentInfo;
  notifications: { pending: NotificationEvent[] };
}

// The kind vestad reports for a known device. Unlike the client-reported ClientKind (frames.ts),
// this can be "unknown" for a device that connected without identifying its surface.
export type DeviceKind = "web" | "mobile" | "desktop" | "unknown";

// The macro place a device reverse geocoded for its position, with the OS geocoder. Any part may
// be null (a fix at sea has no city).
export interface DevicePlace {
  city: string | null;
  region: string | null;
  country: string | null;
}

// A device-reported position: one shape on the client_context frame, the device context report,
// and the roster.
export interface DevicePosition {
  latitude: number;
  longitude: number;
  accuracyM: number | null;
  place: DevicePlace | null;
}

// One device in the gateway-global registry: identity plus whether it currently holds a live /sync
// connection, or when it last did. The push token is never on the wire; `pushEnabled` is the only
// push signal. `descriptor` is null until a device connects and names itself. `timezone` and
// `position` are what the device itself reported (its IANA zone; with the user's opt-in, its
// position and place), `positionAt` the instant of the report that last changed it; null until
// reported.
export interface DeviceInfo {
  id: string;
  kind: DeviceKind;
  descriptor: string | null;
  present: boolean;
  lastSeen: string;
  pushEnabled: boolean;
  timezone: string | null;
  position: DevicePosition | null;
  positionAt: string | null;
}

export interface Tree {
  gateway: GatewayInfo;
  agents: Record<string, AgentNode>;
  devices: DeviceInfo[];
}
