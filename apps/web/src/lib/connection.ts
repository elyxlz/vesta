import type { ConnectionConfig } from "@vesta/core";
import { native } from "./native";
import { useCredentialStorage } from "@/stores/use-credential-storage";
import { errorMessage } from "./utils";

export type { ConnectionConfig };

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

// ── Storage backend ────────────────────────────────────────────
// The bridge owns persistence (Electron: json in userData via the preload;
// browser: localStorage). `cached` gives the sync accessors their value;
// AuthProvider awaits initConnection before anything reads it. The session
// logic (refresh, expiry, token carriers) lives in @vesta/core over these
// accessors (see api/client.ts). A write that fails is shown in App Settings
// (the credential storage card), since the session it lost would otherwise
// vanish silently at the next launch.
let cached: ConnectionConfig | null | undefined;

function persist(operation: () => Promise<void>, failureMessage: string): void {
  const { setWriteError } = useCredentialStorage.getState();
  void Promise.resolve()
    .then(operation)
    .then(
      () => setWriteError(null),
      (cause: unknown) =>
        setWriteError(
          `${failureMessage}: ${errorMessage(cause, "unknown error")}`,
        ),
    );
}

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

/**
 * Persist a hosted (vesta.run) connection: the PKCE-minted access token, no
 * refresh token. `url` is this gateway's own origin (the SPA talks to its own
 * vestad). On expiry the app re-authorizes rather than refreshing.
 */
export function setHostedConnection(
  url: string,
  accessToken: string,
  expiresIn: number,
): void {
  restoreConnection({
    url: url.replace(/\/+$/, ""),
    accessToken,
    refreshToken: "",
    expiresAt: Date.now() + expiresIn * 1000,
    hosted: true,
  });
}

/** Write a whole config as the active connection: a freshly minted session, a
 * saved gateway restored with its tokens verbatim (expiry included), or the
 * session's own token rotation. The session revives an expired one on the next call. */
export function restoreConnection(config: ConnectionConfig): void {
  cached = config;
  persist(
    () => native.connectionStore.write(config),
    "could not save the active gateway",
  );
}

export function setConnection(
  url: string,
  accessToken: string,
  refreshToken: string,
  expiresIn: number,
): void {
  restoreConnection({
    url: url.replace(/\/+$/, ""),
    accessToken,
    refreshToken,
    expiresAt: Date.now() + expiresIn * 1000,
  });
}

export function clearConnection(): void {
  cached = null;
  persist(
    () => native.connectionStore.clear(),
    "could not clear the active gateway",
  );
}
