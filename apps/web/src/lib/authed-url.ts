import { getConnection } from "./connection";
import { ensureFreshToken } from "./token-refresh";

// The one place a token is stamped into a URL: socket handshakes and media-element requests
// cannot carry an Authorization header, so the token rides the query string. Refreshing here is
// what makes it impossible for a call site to dial with a token that expired while the client
// was away; the http client runs the same pre-flight on its own path.
async function withToken(
  path: string,
  query: URLSearchParams,
  protocol: "http" | "ws",
): Promise<string> {
  await ensureFreshToken();
  const conn = getConnection();
  if (!conn) throw new Error("not connected to vestad");
  query.set("token", conn.accessToken);
  const base = protocol === "ws" ? conn.url.replace(/^http/, "ws") : conn.url;
  return `${base}${path}?${query.toString()}`;
}

export function websocketUrl(
  path: string,
  query = new URLSearchParams(),
): Promise<string> {
  return withToken(path, query, "ws");
}

export function mediaUrl(
  path: string,
  query = new URLSearchParams(),
): Promise<string> {
  return withToken(path, query, "http");
}
