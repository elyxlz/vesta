// Every gateway DTO lives once in @vesta/core; these names keep mobile's import paths stable.
// LEGACY(remove-when: the chat-session epic points call sites at @vesta/core directly): delete
// this module then.
export type {
  Account,
  AgentBackupSettings,
  AgentCatalogs,
  BackupInfo,
  ConnectionConfig,
  FieldPredicate,
  FileReadResponse,
  FileTreeEntry,
  GatewayEndpointInfo as GatewayInfo,
  GatewaySettings,
  HostMount,
  NotificationInterruptRule,
  Personality,
  PersonalityCatalog,
  ProviderCatalog,
  ProviderCatalogEntry as ProviderEntry,
  ProviderContextPolicy as ProviderContext,
  ProviderContextPreset as ContextPreset,
  SettingDef,
  Usage,
  UsageMeter,
  VoiceStatus,
} from "@vesta/core";
