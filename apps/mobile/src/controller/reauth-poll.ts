import { isTokenExpiringSoon } from "@/api/client";
import type { ConnectionConfig } from "@/api/types";

export interface RefreshDeps {
  getConnection: () => ConnectionConfig | null;
  refreshAccessToken: () => Promise<boolean>;
}

// Pre-flight for a socket connect: rotate the stored token when it is close to expiring, so a
// client returning after a long background does not spend its backoff presenting a dead one.
// Best effort, since a failed refresh must still attempt the connect.
export async function refreshIfExpiring(deps: RefreshDeps): Promise<void> {
  const connection = deps.getConnection();
  if (connection && isTokenExpiringSoon(connection)) {
    await deps.refreshAccessToken();
  }
}

export interface ReauthDeps {
  getConnection: () => ConnectionConfig | null;
  refreshAccessToken: () => Promise<boolean>;
  reauth: (token: string) => void;
}

// One reauth tick over the live socket: when the current token is close to expiring, refresh
// it and hand the fresh token to the controller in-band. A no-op while the token is still
// fresh or when the refresh cannot complete, so the socket is never torn down to rotate a token.
export async function runReauthCheck(deps: ReauthDeps): Promise<void> {
  const connection = deps.getConnection();
  if (!connection || !isTokenExpiringSoon(connection)) return;
  if (!(await deps.refreshAccessToken())) return;
  const fresh = deps.getConnection();
  if (fresh) deps.reauth(fresh.accessToken);
}
