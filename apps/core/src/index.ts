export {
  clientAheadOfGateway,
  clientBelowMinimum,
  compareReleaseVersions,
  resolveClientVersion,
} from "./protocol/release-version"

export {
  extractWhatsNew,
  fetchReleaseNotes,
  filterReleaseNotes,
  parseReleaseNotes,
} from "./release-notes/release-notes"
export type { ReleaseNote } from "./release-notes/release-notes"

export { parseAnsi, resolveAnsiColor, stripAnsi } from "./ansi/ansi"
export type { AnsiColor, AnsiSpan, AnsiStyle } from "./ansi/ansi"

export type {
  AgentActivityState,
  AgentInfo,
  AgentNode,
  AgentOperation,
  AgentStatus,
  BuildPhase,
  DeviceInfo,
  DeviceKind,
  DevicePlace,
  DevicePosition,
  GatewayInfo,
  GatewayLan,
  GatewayOperation,
  GatewayOperationPhase,
  ReleaseChannel,
  ServiceInfo,
  Tree,
} from "./protocol/tree"
export type { InputMethod, NotificationEvent, VestaEvent } from "./protocol/events"
export type { UserNotificationDelta, DevicesDelta, Delta } from "./protocol/deltas"
export {
  PILL_FALLBACK_ICON,
  PILL_KIND_ICONS,
  pillDisplayLine,
  type PillContent,
  type PillNotification,
} from "./notifications-pill/notifications-pill"
export {
  fetchUserNotifications,
  feedHasUnseen,
  markUserNotificationsSeen,
  splitBySeen,
  type LoggedUserNotification,
} from "./notifications-pill/user-notification-feed"
export { parseServerFrame } from "./protocol/parse"
export type { ParsedFrame } from "./protocol/parse"
export { selectDevices, devicesEqual } from "./tree/devices"
export {
  gatewayOperationLabel,
  gatewayOperationsEqual,
  selectGatewayOperation,
} from "./tree/gateway-operation"

export { createReplica } from "./replica/store"
export type { Replica } from "./replica/store"

export { ApiError, createHttpClient } from "./transport/http"
export type { FetchLike, HttpClient, HttpDeps } from "./transport/http"
export type { SocketLike, SyncSocketDeps, SyncState } from "./transport/socket"
export type { DeviceContext } from "./protocol/frames"
export { readSse } from "./transport/sse"
export type { SseDeps, SseHandle, StreamEvent } from "./transport/sse"

export type { ForegroundSignal } from "./adapters/types"

export { PACING, typingDelay } from "./pacing/pacing"

export { RESTART_REASONS, restartBody } from "./lifecycle/restart-reasons"
export type { RestartBody, RestartReason } from "./lifecycle/restart-reasons"

export {
  notificationRowKey,
  parseNotificationContent,
} from "./notification-content/notification-content"
export type {
  NotificationContent,
  NotificationView,
} from "./notification-content/notification-content"

export {
  TRIM_HISTORY_KEEP,
  TRIM_HISTORY_SETTLE_MS,
  beginSend,
  commitPacedChat,
  foldLiveEvent,
  initialChatState,
  markSend,
  prependPage,
  seedTail,
  trimTail,
} from "./chat/chat-stream-model"
export type { ChatMessage, ChatState, HistoryPage, SendState } from "./chat/chat-stream-model"

export {
  BUBBLE_GROUP_TIME_GAP_MS,
  chatMessageSide,
  startsNewBubbleGroup,
} from "./chat/bubble-grouping"
export type { ChatMessageSide } from "./chat/bubble-grouping"

export { createChatSocket } from "./chat/chat-socket"
export type {
  ChatSocket,
  ChatSocketCallbacks,
  ChatSocketDeps,
  ChatSocketState,
} from "./chat/chat-socket"

export { sendMessage } from "./intents/send-message"
export type { IdGenerator, SendFailure, SendMessageBody, SentMessage } from "./intents/send-message"

export {
  checkForGatewayUpdate,
  dismissGatewayUpdate,
  triggerGatewayRestart,
  triggerGatewayUpdate,
} from "./intents/gateway-update"

export {
  createServiceKeyCache,
  isKeyFresh,
  mintServiceKey,
  serviceKeyPathUrl,
} from "./service-keys/service-keys"
export type { CachedServiceKey, ServiceKey, ServiceKeyCache } from "./service-keys/service-keys"

export { rosterFromTree, rostersEqual } from "./tree/roster"
export type { AgentRow } from "./tree/roster"

export {
  agentIsConnectable,
  agentIsDown,
  agentNeedsUser,
  agentOperationLabel,
  agentOrbState,
  agentStatusKind,
  agentStatusLabel,
  orbIsLive,
} from "./agent-status/agent-status"
export type { AgentStatusKind, OrbVisualState } from "./agent-status/agent-status"

export { ORB_GRADIENT_ANGLE_DEG, orbVisual } from "./orb/orb"
export type { OrbHighlight, OrbPoint, OrbVisual } from "./orb/orb"

export {
  buildBackupTimeline,
  formatSnapshotStamp,
  parseBackupKind,
  parseSnapshotStamp,
} from "./backups/backup-timeline"
export type {
  BackupKind,
  BackupTimelinePoint,
  BackupTimelineRow,
  RestoreEligibility,
} from "./backups/backup-timeline"

export {
  CLAUDE_ALIASES,
  canonicalClaudeModel,
  normalizeProviderInfo,
  providerPutBody,
  resolveProviderIdentity,
} from "./provider/provider"
export type {
  ProviderAuthKind,
  ProviderContextPolicy,
  ProviderContextPreset,
  ProviderInfo,
  ProviderIdentity,
  ProviderInfoWire,
  ProviderKind,
  ProviderManifest,
  ProviderManifestEntry,
  ProviderPutBody,
  ProviderSelection,
} from "./provider/provider"

export { createController } from "./controller/controller"
export type { Controller, ControllerDeps } from "./controller/controller"
