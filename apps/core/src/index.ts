export {
  compareReleaseVersions,
  resolveClientVersion,
} from "./protocol/release-version";

export {
  fetchReleaseNotes,
  filterReleaseNotes,
} from "./release-notes/release-notes";
export type { ReleaseNote } from "./release-notes/release-notes";

export { parseAnsi, resolveAnsiColor } from "./ansi/ansi";
export type { AnsiColor, AnsiStyle } from "./ansi/ansi";

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
  GatewayOperation,
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
export type { UserNotificationDelta, Delta } from "./protocol/deltas";
export {
  PILL_FALLBACK_ICON,
  PILL_KIND_ICONS,
  pillDisplayLine,
  type PillNotification,
} from "./notifications-pill/notifications-pill";
export { type LoggedUserNotification } from "./notifications-pill/user-notification-feed";
export {
  feedSections,
  feedUnseen,
  feedView,
  type FeedSections,
  type FeedView,
  type NotificationFeed,
} from "./notifications-pill/notification-feed";
export { parseServerFrame } from "./protocol/parse";
export { selectDevices, devicesEqual } from "./tree/devices";
export {
  gatewayOperationLabel,
  gatewayOperationsEqual,
  selectGatewayOperation,
} from "./tree/gateway-operation";

export { createReplica } from "./replica/store";

export { ApiError, jsonInit } from "./transport/http";
export type { FetchLike, HttpClient } from "./transport/http";
export type { SyncState } from "./transport/socket";
export type { SocketLike } from "./transport/websocket";
export type { DeviceContext } from "./protocol/frames";
export { readSse } from "./transport/sse";
export type { SseHandle, StreamEvent } from "./transport/sse";

export type { ForegroundSignal } from "./adapters/types";

export { PACING, typingDelay } from "./pacing/pacing";

export { agentHoldKey, createKeyedHoldStore } from "./holds/keyed-hold";
export type { KeyedHoldStore } from "./holds/keyed-hold";

export type { RestartReason } from "./lifecycle/restart-reasons";

export {
  notificationRowKey,
  parseNotificationContent,
} from "./notification-content/notification-content";
export type { NotificationView } from "./notification-content/notification-content";

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
} from "./chat/chat-stream-model";

export {
  appChatAttachmentPath,
  attachmentKind,
  formatBytes,
  MAX_ATTACHMENT_BYTES,
  MAX_ATTACHMENTS_PER_MESSAGE,
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
} from "./attachments/attachment-draft";
export type { DraftAttachment } from "./attachments/attachment-draft";

export { chatMessageSide, startsNewBubbleGroup } from "./chat/bubble-grouping";
export type { ChatMessageSide } from "./chat/bubble-grouping";

export { createChatSocket } from "./chat/chat-socket";

export { createVoiceSession } from "./voice/voice-session";
export type { VoiceMode, VoiceSession } from "./voice/voice-session";
export type { AudioCapture } from "./voice/stt-session";
export type { SpeechPlayer } from "./voice/tts-queue";

export { sendMessage } from "./intents/send-message";
export type { SendFailure } from "./intents/send-message";

// The gateway session: what every client holds, with the app injecting only persistence.
export {
  ConnectError,
  GATEWAY_CONNECT_TIMEOUT_MS,
  REAUTH_POLL_MS,
  TOKEN_REFRESH_BUFFER_MS,
  createSession,
  isTokenExpiringSoon,
  mintConnection,
  normalizeGatewayUrl,
  refreshConnection,
  runReauthCheck,
} from "./session/session";
export type { ConnectionConfig, Session } from "./session/session";

// The gateway REST catalog: every route once, as a function taking the app's HttpClient first.
export {
  AgentStatusError,
  agentPath,
  createAgent,
  deleteAgent,
  fetchUsage,
  renameAgent,
  restartAgent,
  startAgent,
  stopAgent,
  waitUntilReady,
  waitUntilRunning,
} from "./api/agents";
export type { Account, Usage, UsageCredits, UsageMeter } from "./api/agents";
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
export type { BackupInfo } from "./api/backups";
export {
  getNotificationInterruptRules,
  setNotificationInterruptRules,
} from "./api/config-rules";
export type {
  FieldPredicate,
  NotificationInterruptRule,
} from "./api/config-rules";
export {
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
  checkForGatewayUpdate,
  dismissGatewayUpdate,
  fetchGatewayInfo,
  fetchGatewaySettings,
  triggerGatewayRestart,
  triggerGatewayUpdate,
  updateGatewaySettings,
} from "./api/gateway";
export type { GatewayEndpointInfo, GatewaySettings } from "./api/gateway";
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
export { registerMobileDevice, unregisterMobileDevice } from "./api/devices";

export {
  createServiceKeyCache,
  serviceKeyPathUrl,
} from "./service-keys/service-keys";
export type { ServiceKeyCache } from "./service-keys/service-keys";

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
} from "./agent-status/agent-status";
export type { OrbVisualState } from "./agent-status/agent-status";

export { ORB_GRADIENT_ANGLE_DEG, orbVisual } from "./orb/orb";
export type { OrbMotion } from "./orb/orb";

export {
  buildBackupTimeline,
  formatSnapshotStamp,
  parseBackupKind,
} from "./backups/backup-timeline";
export type {
  BackupTimelinePoint,
  BackupTimelineRow,
} from "./backups/backup-timeline";

export {
  CLAUDE_ALIASES,
  canonicalClaudeModel,
  resolveProviderIdentity,
} from "./provider/provider";
export type {
  ProviderContextPolicy,
  ProviderContextPreset,
  ProviderInfo,
  ProviderIdentity,
  ProviderKind,
  ProviderCatalog,
  ProviderCatalogEntry,
  ProviderSelection,
  ProviderInfoWire,
} from "./provider/provider";

export { createController } from "./controller/controller";
export type { Controller, ControllerDeps } from "./controller/controller";
