import { jsonInit, type HttpClient } from "../transport/http";
import { agentPath } from "./agents";

// A user-granted host filesystem access: a host path bind-mounted into the agent's container at
// `container_path` (defaults to `host_path` when unset by the caller), read-only unless `writable`.
export interface HostMount {
  host_path: string;
  container_path: string;
  writable: boolean;
}

// Read the agent's host filesystem grants (GET /mounts).
export async function getAgentMounts(
  http: HttpClient,
  name: string,
): Promise<HostMount[]> {
  const response = await http.json<{ mounts: HostMount[] }>(
    agentPath(name, "/mounts"),
  );
  return response.mounts;
}

// Replace the agent's host filesystem grants (PUT /mounts). The server validates each grant (host
// path exists, container path is not protected, no duplicate container paths) and returns the
// validated list plus whether a restart is needed to apply it (always true today).
export async function setAgentMounts(
  http: HttpClient,
  name: string,
  mounts: HostMount[],
): Promise<{ mounts: HostMount[]; restartRequired: boolean }> {
  const response = await http.json<{
    mounts: HostMount[];
    restart_required: boolean;
  }>(agentPath(name, "/mounts"), jsonInit("PUT", { mounts }));
  return {
    mounts: response.mounts,
    restartRequired: response.restart_required,
  };
}

// Existing host folders vestad suggests sharing (GET /host/folders), so the user does not hand-type
// a path. Host-level (not agent-scoped).
export async function getHostFolderSuggestions(
  http: HttpClient,
): Promise<string[]> {
  const response = await http.json<{ folders: string[] }>("/host/folders");
  return response.folders;
}
