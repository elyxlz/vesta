export {
  clientAheadOfGateway,
  clientBelowMinimum,
  compareReleaseVersions,
  resolveClientVersion,
} from "./protocol/release-version";

export {
  extractWhatsNew,
  fetchReleaseNotes,
  filterReleaseNotes,
  parseReleaseNotes,
} from "./release-notes/release-notes";
export type { ReleaseNote } from "./release-notes/release-notes";

export { parseAnsi, resolveAnsiColor, stripAnsi } from "./ansi/ansi";
export type { AnsiColor, AnsiSpan, AnsiStyle } from "./ansi/ansi";

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
  RateLimitedInfo,
  ReleaseChannel,
  ServiceInfo,
  Tree,
} from "./protocol/tree";
export type {
  InputMethod,
  NotificationEvent,
  VestaEvent,
} from "./protocol/events";
export type {
  UserNotificationDelta,
  DevicesDelta,
  Delta,
} from "./protocol/deltas";
export {
  PILL_FALLBACK_ICON,
  PILL_KIND_ICONS,
  pillDisplayLine,
  type PillContent,
  type PillNotification,
} from "./notifications-pill/notifications-pill";
export {
  fetchUserNotifications,
  feedHasUnseen,
  loggedFromDelta,
  markUserNotificationsSeen,
  splitBySeen,
  type LoggedUserNotification,
} from "./notifications-pill/user-notification-feed";
export {
  EMPTY_FEED,
  feedNeedsMarkSeen,
  feedSections,
  feedUnseen,
  feedView,
  reduceFeed,
  type FeedAction,
  type FeedSections,
  type FeedView,
  type NotificationFeed,
} from "./notifications-pill/notification-feed";
export { parseServerFrame } from "./protocol/parse";
export type { ParsedFrame } from "./protocol/parse";
export { selectDevices, devicesEqual } from "./tree/devices";
export {
  gatewayOperationLabel,
  gatewayOperationsEqual,
  selectGatewayOperation,
} from "./tree/gateway-operation";

export { createReplica } from "./replica/store";
export type { Replica } from "./replica/store";

export { ApiError, createHttpClient, jsonInit } from "./transport/http";
export type { FetchLike, HttpClient, HttpDeps } from "./transport/http";
export type { SyncSocketDeps, SyncState } from "./transport/socket";
export { adaptWebSocket } from "./transport/websocket";
export type { SocketLike } from "./transport/websocket";
export type { DeviceContext } from "./protocol/frames";
export { readSse, drainSsePipeline } from "./transport/sse";
export type { SseDeps, SseHandle, StreamEvent } from "./transport/sse";

export type { ForegroundSignal } from "./adapters/types";

export { PACING, typingDelay } from "./pacing/pacing";

export { agentHoldKey, createKeyedHoldStore } from "./holds/keyed-hold";
export type { HeldCells, KeyedHoldStore } from "./holds/keyed-hold";

export { RESTART_REASONS, restartBody } from "./lifecycle/restart-reasons";
export type { RestartBody, RestartReason } from "./lifecycle/restart-reasons";

export {
  notificationRowKey,
  parseNotificationContent,
} from "./notification-content/notification-content";
export type {
  NotificationContent,
  NotificationView,
} from "./notification-content/notification-content";

export {
  TRIM_HISTORY_SETTLE_MS,
  beginSend,
  commitPacedChat,
  foldLiveEvent,
  initialChatState,
  markSend,
  prependPage,
  seedTail,
  trimTail,
  retryableSends,
} from "./chat/chat-stream-model";
export type {
  ChatMessage,
  ChatState,
  HistoryPage,
  RetryableSend,
  SendState,
} from "./chat/chat-stream-model";

export {
  appChatAttachmentPath,
  attachmentKind,
  formatBytes,
  INITIAL_CHUNK_BYTES,
  MAX_ATTACHMENT_BYTES,
  MAX_ATTACHMENTS_PER_MESSAGE,
  MAX_CHUNK_UPLOAD_BYTES,
  MIN_CHUNK_BYTES,
} from "./attachments/attachment-model";
export type {
  AttachmentKind,
  ChatAttachment,
} from "./attachments/attachment-model";
export { UploadError, uploadAttachment } from "./attachments/upload";
export type {
  Connectivity,
  UploadCallbacks,
  UploadDeps,
  UploadErrorReason,
  UploadHandle,
  UploadMeta,
  UploadRunState,
} from "./attachments/upload";
export {
  addDraft,
  draftsReady,
  draftTotalBytes,
  failDraft,
  finalizeDraft,
  removeDraft,
  setDraftProgress,
  setDraftWaiting,
  uploadedAttachments,
  uploadedIds,
} from "./attachments/attachment-draft";
export type {
  DraftAttachment,
  DraftFile,
  DraftStatus,
} from "./attachments/attachment-draft";

export {
  BUBBLE_GROUP_TIME_GAP_MS,
  chatMessageSide,
  startsNewBubbleGroup,
} from "./chat/bubble-grouping";
export type { ChatMessageSide } from "./chat/bubble-grouping";

export { createChatSocket } from "./chat/chat-socket";
export type {
  ChatSocket,
  ChatSocketCallbacks,
  ChatSocketDeps,
  ChatSocketState,
} from "./chat/chat-socket";

export { createVoiceSession } from "./voice/voice-session";
export type {
  VoiceMode,
  VoiceSession,
  VoiceSessionCallbacks,
  VoiceSessionDeps,
  VoiceSessionSettings,
} from "./voice/voice-session";
export { createSttSession, MAX_PENDING_AUDIO_BYTES } from "./voice/stt-session";
export type {
  AudioCapture,
  SttSession,
  VoiceSocketLike,
} from "./voice/stt-session";
export { createTtsQueue } from "./voice/tts-queue";
export type { SpeechPlayer, TtsQueue } from "./voice/tts-queue";

export { sendMessage } from "./intents/send-message";
export type {
  IdGenerator,
  SendFailure,
  SendMessageBody,
  SentMessage,
} from "./intents/send-message";

// The gateway session: what every client holds, with the app injecting only persistence.
export {
  ConnectError,
  GATEWAY_CONNECT_TIMEOUT_MS,
  NOT_CONNECTED,
  REAUTH_POLL_MS,
  TOKEN_REFRESH_BUFFER_MS,
  createSession,
  isTokenExpiringSoon,
  mintConnection,
  normalizeGatewayUrl,
  refreshConnection,
  runReauthCheck,
} from "./session/session";
export type {
  ConnectFailure,
  ConnectionConfig,
  RefreshOutcome,
  RefreshResult,
  Session,
  SessionDeps,
} from "./session/session";

// The gateway REST catalog: every route once, as a function taking the app's HttpClient first.
export {
  AgentStatusError,
  agentPath,
  createAgent,
  deleteAgent,
  fetchAgentStatus,
  fetchUsage,
  renameAgent,
  restartAgent,
  startAgent,
  stopAgent,
  waitUntilReady,
  waitUntilRunning,
} from "./api/agents";
export type {
  Account,
  AgentStatusResponse,
  Usage,
  UsageCredits,
  UsageMeter,
} from "./api/agents";
export {
  completeClaudeOAuth,
  completeOpenAIOAuth,
  fetchAgentClaudeModels,
  fetchClaudeModelsWithCredentials,
  fetchOpenRouterModels,
  getProvider,
  provisionAgent,
  setContextWindow,
  setModel,
  signOutProvider,
  startClaudeOAuth,
  startOpenAIOAuth,
  validateOpenRouterKey,
} from "./api/provider";
export type {
  ClaudeOAuthStart,
  OpenAIOAuthStart,
  OpenRouterModelOption,
  ProviderResource,
} from "./api/provider";
export {
  createBackup,
  deleteBackup,
  fetchAgentBackupSettings,
  listBackups,
  restoreBackup,
  setAgentBackupSettings,
} from "./api/backups";
export type { AgentBackupSettings, BackupInfo } from "./api/backups";
export {
  getNotificationInterruptRules,
  setNotificationInterruptRules,
} from "./api/config-rules";
export type {
  FieldPredicate,
  NotificationInterruptRule,
} from "./api/config-rules";
export {
  chatHistoryPath,
  chatSocketPath,
  fetchChatHistory,
  fetchInternalsHistory,
  getNotificationHistory,
} from "./api/history";
export { fetchFileTree, readFile, writeFile } from "./api/files";
export type { FileReadResponse, FileTreeEntry } from "./api/files";
export {
  getAgentMounts,
  getHostFolderSuggestions,
  setAgentMounts,
} from "./api/mounts";
export type { HostMount } from "./api/mounts";
export {
  VERSION_CHECK_TIMEOUT_MS,
  checkForGatewayUpdate,
  dismissGatewayUpdate,
  fetchGatewayInfo,
  fetchGatewaySettings,
  triggerGatewayRestart,
  triggerGatewayUpdate,
  updateGatewaySettings,
} from "./api/gateway";
export type {
  GatewayEndpointInfo,
  GatewaySettings,
  GatewayUpdateOutcome,
} from "./api/gateway";
export {
  contextForModel,
  fetchPersonalities,
  fetchProviderCatalog,
} from "./api/catalogs";
export type { Personality, PersonalityCatalog } from "./api/catalogs";
export {
  fetchSttUsage,
  fetchTtsUsage,
  fetchVoiceStatus,
  prepareSpeech,
  setVoiceEnabled,
  setVoiceSetting,
  sttListenPath,
  ttsStreamPath,
} from "./api/voice";
export type {
  SettingDef,
  SttUsage,
  TtsUsage,
  VoiceDomain,
  VoiceStatus,
} from "./api/voice";
export { agentLogsPath, gatewayLogsPath } from "./api/logs";
export {
  registerMobileDevice,
  reportDeviceContext,
  unregisterMobileDevice,
} from "./api/devices";
export type { MobileDeviceRegistration } from "./api/devices";

export {
  createServiceKeyCache,
  isKeyFresh,
  mintServiceKey,
  serviceKeyPathUrl,
} from "./service-keys/service-keys";
export type {
  CachedServiceKey,
  ServiceKey,
  ServiceKeyCache,
} from "./service-keys/service-keys";

export { rosterFromTree, rostersEqual } from "./tree/roster";
export type { AgentRow } from "./tree/roster";

export {
  agentIsConnectable,
  agentIsDown,
  agentNeedsUser,
  agentOperationLabel,
  agentOrbState,
  agentStatusKind,
  agentStatusLabel,
  formatResetTime,
  orbIsLive,
} from "./agent-status/agent-status";
export type {
  AgentStatusKind,
  OrbVisualState,
} from "./agent-status/agent-status";

export { ORB_GRADIENT_ANGLE_DEG, orbVisual } from "./orb/orb";
export type { OrbHighlight, OrbMotion, OrbPoint, OrbVisual } from "./orb/orb";

export {
  buildBackupTimeline,
  formatSnapshotStamp,
  parseBackupKind,
  parseSnapshotStamp,
} from "./backups/backup-timeline";
export type {
  BackupKind,
  BackupTimelinePoint,
  BackupTimelineRow,
  RestoreEligibility,
} from "./backups/backup-timeline";

export {
  CLAUDE_ALIASES,
  canonicalClaudeModel,
  normalizeProviderInfo,
  providerPutBody,
  resolveProviderIdentity,
} from "./provider/provider";
export type {
  ProviderAuthKind,
  ProviderContextPolicy,
  ProviderContextPreset,
  ProviderInfo,
  ProviderIdentity,
  ProviderInfoWire,
  ProviderKind,
  ProviderCatalog,
  ProviderCatalogEntry,
  ProviderPutBody,
  ProviderSelection,
} from "./provider/provider";

export { createController } from "./controller/controller";
export type { Controller, ControllerDeps } from "./controller/controller";
