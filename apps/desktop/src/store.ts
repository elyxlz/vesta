import { app, safeStorage } from "electron";
import fs from "node:fs/promises";
import path from "node:path";

const STORE_VERSION = 1;
const CONNECTION_FILE = "connection.json";
const RECENT_GATEWAYS_FILE = "recent-gateways.json";

interface EncryptedStore {
  version: number;
  encrypted: string;
}

function storePath(filename: string): string {
  return path.join(app.getPath("userData"), filename);
}

/**
 * Whether the OS keeps the store's encryption key out of reach of other local processes: the
 * Keychain, DPAPI, or a Linux secret service. Electron's Linux `basic_text` backend encrypts with
 * a hardcoded key, so it persists but does not protect; the renderer shows a warning for it.
 */
export function storageBackendIsSecure(
  platform: string,
  encryptionAvailable: boolean,
  linuxBackend: string,
): boolean {
  if (!encryptionAvailable) return false;
  if (platform !== "linux") return true;
  return ["gnome_libsecret", "kwallet", "kwallet5", "kwallet6"].includes(
    linuxBackend,
  );
}

export function credentialStorageIsSecure(): boolean {
  const linuxBackend =
    process.platform === "linux"
      ? safeStorage.getSelectedStorageBackend()
      : "unknown";
  return storageBackendIsSecure(
    process.platform,
    safeStorage.isEncryptionAvailable(),
    linuxBackend,
  );
}

// The store degrades rather than refuses: encrypted with whatever backend the OS offers, and
// plain JSON when it offers none, so a session always survives a relaunch.
function payload(value: unknown): unknown {
  if (!safeStorage.isEncryptionAvailable()) return value;
  return {
    version: STORE_VERSION,
    encrypted: safeStorage
      .encryptString(JSON.stringify(value))
      .toString("base64"),
  };
}

function parseEncryptedStore(value: unknown): EncryptedStore | null {
  if (value === null || typeof value !== "object") return null;
  if (
    !("version" in value) ||
    value.version !== STORE_VERSION ||
    !("encrypted" in value) ||
    typeof value.encrypted !== "string"
  ) {
    return null;
  }
  return { version: STORE_VERSION, encrypted: value.encrypted };
}

async function writeStore(filename: string, value: unknown): Promise<void> {
  const target = storePath(filename);
  await fs.mkdir(path.dirname(target), { recursive: true, mode: 0o700 });
  const temporary = `${target}.tmp`;
  await fs.writeFile(temporary, JSON.stringify(payload(value)), {
    encoding: "utf8",
    mode: 0o600,
  });
  await fs.rename(temporary, target);
}

async function readStore(filename: string): Promise<unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(await fs.readFile(storePath(filename), "utf8"));
  } catch {
    return null;
  }

  const encrypted = parseEncryptedStore(parsed);
  if (encrypted) {
    try {
      const decrypted = safeStorage.decryptString(
        Buffer.from(encrypted.encrypted, "base64"),
      );
      return JSON.parse(decrypted);
    } catch {
      return null;
    }
  }

  // A plain store (written while no encryption backend was available) is encrypted in place as
  // soon as one is.
  if (safeStorage.isEncryptionAvailable()) {
    try {
      await writeStore(filename, parsed);
    } catch (cause) {
      console.warn(`could not encrypt plain ${filename}`, cause);
    }
  }
  return parsed;
}

async function clearStore(filename: string): Promise<void> {
  await fs.rm(storePath(filename), { force: true });
}

export function readConnection(): Promise<unknown> {
  return readStore(CONNECTION_FILE);
}

export function writeConnection(value: unknown): Promise<void> {
  return writeStore(CONNECTION_FILE, value);
}

export function clearConnection(): Promise<void> {
  return clearStore(CONNECTION_FILE);
}

export function readRecentGateways(): Promise<unknown> {
  return readStore(RECENT_GATEWAYS_FILE);
}

export function writeRecentGateways(value: unknown): Promise<void> {
  return writeStore(RECENT_GATEWAYS_FILE, value);
}

export function clearRecentGateways(): Promise<void> {
  return clearStore(RECENT_GATEWAYS_FILE);
}
