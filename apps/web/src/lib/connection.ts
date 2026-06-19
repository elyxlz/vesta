import { isTauri } from "./env";
import type { VestaEvent } from "@/lib/types";

const STORAGE_KEY = "vesta-connection";

/** Parse the one-click connect key from a URL fragment like `#k=<key>`, which
 * `vestad status` embeds so opening the link connects without pasting the key.
 * Pure (takes the raw hash) so it unit-tests without a DOM. Null when absent. */
export function parseConnectKey(hash: string): string | null {
  if (!hash.startsWith("#")) return null;
  return new URLSearchParams(hash.slice(1)).get("k");
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

let storePromise: Promise<import("@tauri-apps/plugin-store").Store> | null =
  null;

function getStore() {
  if (!storePromise) {
    storePromise = import("@tauri-apps/plugin-store").then((m) =>
      m.load("connection.json"),
    );
  }
  return storePromise;
}

// Cache for sync access (authHeaders, apiUrl, wsUrl must be sync)
let cached: ConnectionConfig | null | undefined;

async function readFromStore(): Promise<ConnectionConfig | null> {
  const store = await getStore();
  const val = await store.get<ConnectionConfig>(STORAGE_KEY);
  if (val && val.url && val.accessToken && (val.refreshToken || val.hosted))
    return val;
  return null;
}

async function writeToStore(config: ConnectionConfig): Promise<void> {
  const store = await getStore();
  await store.set(STORAGE_KEY, config);
  await store.save();
}

async function deleteFromStore(): Promise<void> {
  const store = await getStore();
  await store.delete(STORAGE_KEY);
  await store.save();
}

function readFromLocalStorage(): ConnectionConfig | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (
      parsed.url &&
      parsed.accessToken &&
      (parsed.refreshToken || parsed.hosted)
    )
      return parsed;
    return null;
  } catch {
    return null;
  }
}

// ── Public API ─────────────────────────────────────────────────

export async function initConnection(): Promise<void> {
  if (isTauri) {
    cached = await readFromStore();
  } else {
    cached = readFromLocalStorage();
  }
}

export function getConnection(): ConnectionConfig | null {
  if (cached === undefined) {
    // Fallback for sync access before initConnection completes
    cached = readFromLocalStorage();
  }
  return cached;
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

  if (isTauri) {
    writeToStore(config);
  }
  // Always write to localStorage too (sync fallback)
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
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
  if (isTauri) {
    writeToStore(config);
  }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
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
  localStorage.removeItem(STORAGE_KEY);
  if (isTauri) {
    deleteFromStore();
  }
}

export function isConnected(): boolean {
  return getConnection() !== null;
}

export function isTokenExpiringSoon(): boolean {
  const conn = getConnection();
  if (!conn) return false;
  return Date.now() > conn.expiresAt - 5 * 60 * 1000; // 5 min buffer
}

export function authHeaders(): Record<string, string> {
  const conn = getConnection();
  if (!conn) return {};
  return { Authorization: `Bearer ${conn.accessToken}` };
}

export function apiUrl(path: string): string {
  const conn = getConnection();
  if (!conn) throw new Error("not connected to vestad");
  return `${conn.url}${path}`;
}

export interface WsUrlOptions {
  skipHistory?: boolean;
}

export function wsUrl(name: string, opts: WsUrlOptions = {}): string {
  const conn = getConnection();
  if (!conn) throw new Error("not connected to vestad");
  const base = conn.url.replace(/^http/, "ws");
  const params = new URLSearchParams({ token: conn.accessToken });
  if (opts.skipHistory) params.set("skip_history", "1");
  return `${base}/agents/${name}/ws?${params.toString()}`;
}

export async function fetchHistory(
  name: string,
  channel: "app-chat" | "internals",
  cursor: number,
): Promise<{ events: VestaEvent[]; cursor: number | null }> {
  const { apiJson } = await import("@/api/client");
  const params = new URLSearchParams({ channel, cursor: String(cursor) });
  return apiJson(`/agents/${encodeURIComponent(name)}/history?${params}`);
}
