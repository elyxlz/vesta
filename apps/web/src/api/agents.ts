import * as core from "@vesta/core";
import type {
  BuildPhase,
  HistoryPage,
  NotificationEvent,
  NotificationInterruptRule,
  ProviderInfo,
  ProviderSelection,
  RestartReason,
} from "@vesta/core";
import { httpClient } from "./client";

// Every route lives once in @vesta/core; these bind the app's one HttpClient so call sites keep
// their import path. LEGACY(remove-when: the chat-session epic points call sites at @vesta/core
// directly): delete this module then.

export type { BuildPhase, NotificationEvent, ProviderInfo };
export type ProviderResult = ProviderSelection;
export type {
  Account,
  AgentBackupSettings,
  BackupInfo,
  FieldPredicate,
  HostMount,
  NotificationInterruptRule,
  ProviderResource,
  Usage,
  UsageCredits,
  UsageMeter,
} from "@vesta/core";
export { AgentStatusError } from "@vesta/core";

export const setProvider = (
  name: string,
  result: ProviderResult,
  personality?: string,
  timezone?: string,
) => core.provisionAgent(httpClient, name, result, personality, timezone);
export const signOutProvider = (name: string) =>
  core.signOutProvider(httpClient, name);
export const getProvider = (name: string) => core.getProvider(httpClient, name);
export const setModel = (name: string, model: string) =>
  core.setModel(httpClient, name, model);
export const setContextWindow = (name: string, maxContextTokens: number) =>
  core.setContextWindow(httpClient, name, maxContextTokens);
export const createAgent = (name: string) => core.createAgent(httpClient, name);
export const waitUntilRunning = (
  name: string,
  timeoutMs: number,
  pollIntervalMs?: number,
) => core.waitUntilRunning(httpClient, name, timeoutMs, pollIntervalMs);
export const waitUntilReady = (
  name: string,
  timeoutMs: number,
  pollIntervalMs?: number,
) => core.waitUntilReady(httpClient, name, timeoutMs, pollIntervalMs);
export const startAgent = (name: string) => core.startAgent(httpClient, name);
export const stopAgent = (name: string) => core.stopAgent(httpClient, name);
export const restartAgent = (name: string, reason?: RestartReason) =>
  core.restartAgent(httpClient, name, reason);
export const deleteAgent = (name: string) => core.deleteAgent(httpClient, name);
export const renameAgent = (name: string, newName: string) =>
  core.renameAgent(httpClient, name, newName);
export const createBackup = (name: string) =>
  core.createBackup(httpClient, name);
export const listBackups = (name: string) => core.listBackups(httpClient, name);
export const restoreBackup = (name: string, backupId: string) =>
  core.restoreBackup(httpClient, name, backupId);
export const deleteBackup = (name: string, backupId: string) =>
  core.deleteBackup(httpClient, name, backupId);
export const fetchAgentBackupSettings = (name: string) =>
  core.fetchAgentBackupSettings(httpClient, name);
export const setAgentBackupSettings = (name: string, enabled: boolean) =>
  core.setAgentBackupSettings(httpClient, name, enabled);
export const fetchUsage = (name: string) => core.fetchUsage(httpClient, name);
export const getNotificationInterruptRules = (name: string) =>
  core.getNotificationInterruptRules(httpClient, name);
export const setNotificationInterruptRules = (
  name: string,
  rules: NotificationInterruptRule[],
) => core.setNotificationInterruptRules(httpClient, name, rules);
export const getNotificationHistory = (name: string, cursor?: number) =>
  core.getNotificationHistory(httpClient, name, cursor);
export const fetchHistory = (
  name: string,
  channel: "app-chat" | "internals",
  cursor?: number,
): Promise<HistoryPage> =>
  channel === "app-chat"
    ? core.fetchChatHistory(httpClient, name, cursor)
    : core.fetchInternalsHistory(httpClient, name, cursor);
export const getAgentMounts = (name: string) =>
  core.getAgentMounts(httpClient, name);
export const setAgentMounts = (name: string, mounts: core.HostMount[]) =>
  core.setAgentMounts(httpClient, name, mounts);
export const getHostFolderSuggestions = () =>
  core.getHostFolderSuggestions(httpClient);

// Coarse, ordered stages of first-time agent creation reported by vestad while the create POST is in
// flight (core owns the type). The image step (`pulling` on a release build, `building` from a local
// checkout) is the dominant wait.
const BUILD_PHASE_MESSAGES: Record<BuildPhase, string> = {
  pulling: "downloading the agent image...",
  building: "building the agent image...",
  preparing: "preparing agent code...",
  creating: "creating the container...",
  starting: "starting up...",
};

/// Map a build phase to an honest, lowercase status line. A null phase (the
/// create has not reported yet, or has already settled) falls back to a neutral
/// line rather than a fabricated near-done claim.
export function buildPhaseMessage(phase: BuildPhase | null): string {
  return phase === null ? "setting things up..." : BUILD_PHASE_MESSAGES[phase];
}
