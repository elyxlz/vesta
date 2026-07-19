export { PROTOCOL_FLOOR, PROTOCOL_VERSION } from "./protocol/version"

export type {
  AgentActivityState,
  AgentInfo,
  AgentNode,
  AgentStatus,
  BuildPhase,
  GatewayInfo,
  GatewayLan,
  ReleaseChannel,
  ServiceInfo,
  Tree,
} from "./protocol/tree"
export type { InputMethod, NotificationEvent, VestaEvent } from "./protocol/events"
export { encodeFrame, reauthFrame, unwatchFrame, watchFrame } from "./protocol/frames"
export type {
  ClientFrame,
  HelloFrame,
  ReauthFrame,
  SnapshotFrame,
  UnwatchFrame,
  WatchFrame,
} from "./protocol/frames"
export type {
  AgentDelta,
  AgentRemovedDelta,
  AppendDelta,
  Delta,
  NotificationsDelta,
  ResyncDelta,
  StateDelta,
} from "./protocol/deltas"
export { parseServerFrame } from "./protocol/parse"
export type { ParsedFrame } from "./protocol/parse"

export { reduceDelta } from "./replica/reducer"
export { createReplica } from "./replica/store"
export type { Replica } from "./replica/store"
export { createWatchManager } from "./replica/watch"
export type { WatchManager } from "./replica/watch"

export { ApiError, createHttpClient } from "./transport/http"
export type { FetchLike, HttpClient, HttpDeps } from "./transport/http"
export { createSyncSocket } from "./transport/socket"
export type {
  SocketLike,
  SyncSocket,
  SyncSocketCallbacks,
  SyncSocketDeps,
  SyncState,
} from "./transport/socket"
export { readSse } from "./transport/sse"
export type { SseDeps, SseHandle, StreamEvent } from "./transport/sse"

export { PACING, typingDelay } from "./pacing/pacing"

export { isStructured, notificationContent, parseFields } from "./notification-content/notification-content"

export { createSendMessageIntent } from "./intents/types"
export type {
  IdGenerator,
  IntentEnvelope,
  IntentId,
  SendMessageBody,
  SendMessageIntent,
} from "./intents/types"

export type { ForegroundSignal, PushTokenProvider, StorageAdapter } from "./adapters/types"
