import { isTauri } from "./env";
import type { VestaEvent } from "@/lib/types";

const STORAGE_KEY = "vesta-connection";

export interface ConnectionConfig {
  url: string;
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
}

// ── Storage backend ────────────────────────────────────────────

let storePromise: Promise<import("@tauri-apps/plugin-store").Store> | null = null;

function getStore() {
  if (!storePromise) {
    storePromise = import("@tauri-apps/plugin-store").then((m) => m.load("connection.json"));
  }
  return storePromise;
}

// Cache for sync access (authHeaders, apiUrl, wsUrl must be sync)
let cached: ConnectionConfig | null | undefined;

async function readFromStore(): Promise<ConnectionConfig | null> {
  const store = await getStore();
  const val = await store.get<ConnectionConfig>(STORAGE_KEY);
  if (val && val.url && val.accessToken && val.refreshToken) return val;
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
    if (parsed.apiKey && !parsed.accessToken) {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    if (parsed.url && parsed.accessToken && parsed.refreshToken) return parsed;
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
  const config: ConnectionConfig = { url: normalized, accessToken, refreshToken, expiresAt };
  cached = config;

  if (isTauri) {
    writeToStore(config);
  }
  // Always write to localStorage too (sync fallback)
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

export function wsUrl(name: string): string {
  const conn = getConnection();
  if (!conn) throw new Error("not connected to vestad");
  const base = conn.url.replace(/^http/, "ws");
  return `${base}/agents/${name}/ws?token=${encodeURIComponent(conn.accessToken)}`;
}

export async function fetchHistory(
  name: string,
  cursor: number,
): Promise<{ events: VestaEvent[]; cursor: number | null }> {
  const conn = getConnection();
  if (!conn) throw new Error("not connected to vestad");
  const params = new URLSearchParams({ cursor: String(cursor) });
  const res = await fetch(`${conn.url}/agents/${name}/history?${params}`, {
    headers: { Authorization: `Bearer ${conn.accessToken}` },
  });
  if (!res.ok) throw new Error(`history fetch failed: ${res.status}`);
  return res.json();
}
