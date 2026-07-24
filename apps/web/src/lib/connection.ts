import { native } from "./native";

/** Parse the one-click connect key from a URL fragment like `#k=<key>`, which
 * `vestad status` embeds so opening the link connects without pasting the key.
 * Pure (takes the raw hash) so it unit-tests without a DOM. Null when absent. */
export function parseConnectKey(hash: string): string | null {
  if (!hash.startsWith("#")) return null;
  return new URLSearchParams(hash.slice(1)).get("k");
}

/** Split a full connect link (`https://host/app#k=<key>`, printed by `vestad
 * status`) into the vestad origin and the key, so the native app's self-host
 * form can take a single paste instead of two fields. Drops the `/app` path
 * and the fragment to recover the origin. Null when the input isn't a link. */
export function parseConnectLink(
  input: string,
): { host: string; key: string } | null {
  const trimmed = input.trim();
  const hashIndex = trimmed.indexOf("#");
  if (hashIndex === -1) return null;
  const key = parseConnectKey(trimmed.slice(hashIndex));
  if (!key) return null;
  const host = trimmed
    .slice(0, hashIndex)
    .replace(/\/+$/, "")
    .replace(/\/app$/, "");
  if (!host) return null;
  return { host, key };
}

export interface ConnectionConfig {
  url: string;
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
  // Hosted (vesta.run) connections carry NO refresh token — the apex session
  // cookie is the refresh root. On expiry the app re-runs the PKCE authorize
  // flow (see token-refresh.ts) instead of calling vestad /auth/refresh.
  hosted?: boolean;
}

// ── Storage backend ────────────────────────────────────────────
// The bridge owns persistence (Electron: json in userData via the preload;
// browser: localStorage). `cached` gives the sync accessors their value;
// AuthProvider awaits initConnection before anything reads it.
let cached: ConnectionConfig | null | undefined;

// ── Public API ─────────────────────────────────────────────────

export async function initConnection(): Promise<void> {
  cached = await native.connectionStore.read();
}

export function getConnection(): ConnectionConfig | null {
  if (cached === undefined) return null;
  return cached;
}

/** Display hostname of the current connection (falls back to the raw url if it
 * doesn't parse, "" when not connected). */
export function connectionHostname(): string {
  const conn = getConnection();
  if (!conn) return "";
  try {
    return new URL(conn.url).hostname;
  } catch {
    return conn.url;
  }
}

export function setConnection(
  url: string,
  accessToken: string,
  refreshToken: string,
  expiresIn: number,
): void {
  const normalized = url.replace(/\/+$/, "");
  const expiresAt = Date.now() + expiresIn * 1000;
  const config: ConnectionConfig = {
    url: normalized,
    accessToken,
    refreshToken,
    expiresAt,
  };
  cached = config;
  void native.connectionStore.write(config);
}

/**
 * Persist a hosted (vesta.run) connection: the PKCE-minted access token, no
 * refresh token. `url` is this box's own origin (the SPA talks to its own
 * vestad). On expiry the app re-authorizes rather than refreshing.
 */
export function setHostedConnection(
  url: string,
  accessToken: string,
  expiresIn: number,
): void {
  const normalized = url.replace(/\/+$/, "");
  const config: ConnectionConfig = {
    url: normalized,
    accessToken,
    refreshToken: "",
    expiresAt: Date.now() + expiresIn * 1000,
    hosted: true,
  };
  cached = config;
  void native.connectionStore.write(config);
}

export function updateTokens(
  accessToken: string,
  refreshToken: string,
  expiresIn: number,
): void {
  const conn = getConnection();
  if (!conn) return;
  setConnection(conn.url, accessToken, refreshToken, expiresIn);
}

export function clearConnection(): void {
  cached = null;
  void native.connectionStore.clear();
}

export function isTokenExpiringSoon(): boolean {
  const conn = getConnection();
  if (!conn) return false;
  return Date.now() > conn.expiresAt - 5 * 60 * 1000; // 5 min buffer
}
