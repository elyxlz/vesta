export {
  clientAheadOfGateway,
  clientBelowMinimum,
  compareReleaseVersions,
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
  AgentStatus,
  BuildPhase,
  GatewayInfo,
  GatewayLan,
  ReleaseChannel,
  ServiceInfo,
  Tree,
} from "./protocol/tree"
export type { InputMethod, NotificationEvent, VestaEvent } from "./protocol/events"
export type { UserNotificationDelta, Delta } from "./protocol/deltas"

export { createReplica } from "./replica/store"
export type { Replica } from "./replica/store"

export { ApiError, createHttpClient } from "./transport/http"
export type { FetchLike, HttpClient, HttpDeps } from "./transport/http"
export type { SocketLike, SyncSocketDeps, SyncState } from "./transport/socket"
export { readSse } from "./transport/sse"
export type { SseDeps, SseHandle, StreamEvent } from "./transport/sse"

export type { ForegroundSignal } from "./adapters/types"

export { PACING, typingDelay } from "./pacing/pacing"

export { parseNotificationContent } from "./notification-content/notification-content"
export type {
  NotificationContent,
  NotificationView,
} from "./notification-content/notification-content"

export {
  beginSend,
  commitPacedChat,
  foldLiveEvent,
  initialChatState,
  markSend,
  prependPage,
  seedTail,
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
  triggerGatewayRestart,
  triggerGatewayUpdate,
} from "./intents/gateway-update"

export { rosterFromTree, rostersEqual } from "./tree/roster"
export type { AgentRow } from "./tree/roster"

export { normalizeProviderInfo, providerPutBody } from "./provider/provider"
export type {
  ProviderAuthKind,
  ProviderContextPolicy,
  ProviderContextPreset,
  ProviderInfo,
  ProviderInfoWire,
  ProviderKind,
  ProviderManifest,
  ProviderManifestEntry,
  ProviderPutBody,
  ProviderSelection,
} from "./provider/provider"

export { createController } from "./controller/controller"
export type { Controller, ControllerDeps } from "./controller/controller"
