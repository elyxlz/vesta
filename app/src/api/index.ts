export { apiFetch, apiJson } from "./client";
export {
  listAgents,
  agentStatus,
  createAgent,
  startAgent,
  stopAgent,
  restartAgent,
  deleteAgent,
  rebuildAgent,
  createBackup,
  listBackups,
  restoreBackup,
  deleteBackup,
  type BackupInfo,
  waitForReady,
  waitForStopped,
} from "./agents";
export { authenticate, submitAuthCode, type AuthStartResult } from "./auth";
export { streamLogs, stopLogs } from "./logs";
export { connectToServer } from "./server";
export { isNewer, checkAndInstallUpdate } from "./updates";
