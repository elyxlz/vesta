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
  backupAgent,
  restoreAgent,
  waitForReady,
} from "./agents";
export { authenticate, submitAuthCode, type AuthStartResult } from "./auth";
export { streamLogs, stopLogs } from "./logs";
export { connectToServer } from "./server";
export {
  autoSetup,
  checkPlatform,
  setupPlatform,
  runInstallScript,
} from "./platform";
export { isNewer, checkAndInstallUpdate } from "./updates";
