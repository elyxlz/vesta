import { getConnection, isTokenExpiringSoon } from "@/lib/connection";
import { ensureFreshToken } from "@/lib/token-refresh";

// One reauth tick over the live socket: when the stored token is close to expiring, refresh it
// and hand the fresh token to the controller in-band. A no-op while the token is still fresh or
// when the refresh cannot complete, so the socket is never torn down to rotate a token.
export async function runReauthCheck(
  reauth: (token: string) => void,
): Promise<void> {
  if (!isTokenExpiringSoon()) return;
  if ((await ensureFreshToken()) !== "ok") return;
  const conn = getConnection();
  if (conn) reauth(conn.accessToken);
}
