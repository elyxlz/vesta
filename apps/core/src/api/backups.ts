import { jsonInit, type HttpClient } from "../transport/http";
import { drainSsePipeline } from "../transport/sse";
import { agentPath } from "./agents";

export interface BackupInfo {
  id: string;
  agent_name: string;
  backup_type: string;
  created_at: string;
  size: number;
  // The version an update left, on a pre-update snapshot alone; carries a `v` prefix.
  from_version?: string | null;
  // The vestad version that captured the snapshot; absent on pre-stamp snapshots.
  vestad_version?: string | null;
}

export interface AgentBackupSettings {
  enabled: boolean;
  retention: { periodic: number; pre_update_versions: number };
  has_override: boolean;
}

function backupPath(name: string, backupId: string, suffix = ""): string {
  return agentPath(name, `/backups/${encodeURIComponent(backupId)}${suffix}`);
}

// A backup streams its progress as SSE; the call settles when the pipeline reports done or fails.
export async function createBackup(
  http: HttpClient,
  name: string,
): Promise<void> {
  await drainSsePipeline(
    await http.request(agentPath(name, "/backups"), { method: "POST" }),
  );
}

export async function listBackups(
  http: HttpClient,
  name: string,
): Promise<BackupInfo[]> {
  return http.json<BackupInfo[]>(agentPath(name, "/backups"));
}

export async function restoreBackup(
  http: HttpClient,
  name: string,
  backupId: string,
): Promise<void> {
  await drainSsePipeline(
    await http.request(backupPath(name, backupId, "/restore"), {
      method: "POST",
    }),
  );
}

export async function deleteBackup(
  http: HttpClient,
  name: string,
  backupId: string,
): Promise<void> {
  await http.request(backupPath(name, backupId), { method: "DELETE" });
}

export async function fetchAgentBackupSettings(
  http: HttpClient,
  name: string,
): Promise<AgentBackupSettings> {
  return http.json<AgentBackupSettings>(agentPath(name, "/settings/backup"));
}

export async function setAgentBackupSettings(
  http: HttpClient,
  name: string,
  enabled: boolean,
): Promise<AgentBackupSettings> {
  return http.json<AgentBackupSettings>(
    agentPath(name, "/settings/backup"),
    jsonInit("PUT", { enabled }),
  );
}
