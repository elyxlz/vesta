import { getConnection } from "./connection";
import { ensureFreshToken } from "./token-refresh";

// The one place the access token is stamped into a URL: a browser WebSocket sends no headers,
// so a socket handshake carries it in the query string. Refreshing here is what makes it
// impossible for a call site to dial with a token that expired while the client was away;
// the http client runs the same pre-flight on its own path.
export async function websocketUrl(
  path: string,
  query = new URLSearchParams(),
): Promise<string> {
  await ensureFreshToken();
  const conn = getConnection();
  if (!conn) throw new Error("not connected to vestad");
  query.set("token", conn.accessToken);
  return `${conn.url.replace(/^http/, "ws")}${path}?${query.toString()}`;
}
