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

function secureStorageAvailable(): boolean {
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

function encryptedPayload(value: unknown): EncryptedStore {
  if (!secureStorageAvailable()) {
    throw new Error("secure credential storage is unavailable");
  }
  return {
    version: STORE_VERSION,
    encrypted: safeStorage
      .encryptString(JSON.stringify(value))
      .toString("base64"),
  };
}

function parseEncryptedStore(value: unknown): EncryptedStore | null {
  if (value === null || typeof value !== "object") return null;
  const record = value as { version?: unknown; encrypted?: unknown };
  if (
    record.version !== STORE_VERSION ||
    typeof record.encrypted !== "string"
  ) {
    return null;
  }
  return { version: STORE_VERSION, encrypted: record.encrypted };
}

async function writeStore(filename: string, value: unknown): Promise<void> {
  const target = storePath(filename);
  await fs.mkdir(path.dirname(target), { recursive: true, mode: 0o700 });
  const temporary = `${target}.tmp`;
  await fs.writeFile(temporary, JSON.stringify(encryptedPayload(value)), {
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

  // LEGACY(remove-when: MIN_SUPPORTED_CLIENT_VERSION exceeds 0.2.13):
  // Re-encrypt stores written by desktop releases that persisted plain JSON.
  if (secureStorageAvailable()) {
    try {
      await writeStore(filename, parsed);
    } catch (cause) {
      console.warn(`could not encrypt legacy ${filename}`, cause);
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
