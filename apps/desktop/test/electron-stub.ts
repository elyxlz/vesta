import os from "node:os";

export const app = {
  getPath: (): string => process.env.VESTA_TEST_USER_DATA ?? os.tmpdir(),
};

const ENCRYPTED = /^encrypted:(\d+):/;

// Ciphertext names the key that made it; a key older than the current one asks to be re-encrypted.
function currentKey(): string {
  return process.env.VESTA_TEST_KEY_VERSION ?? "1";
}

export const safeStorage = {
  isAsyncEncryptionAvailable: (): Promise<boolean> =>
    Promise.resolve(process.env.VESTA_TEST_ENCRYPTION_AVAILABLE !== "false"),
  getSelectedStorageBackend: (): string =>
    process.env.VESTA_TEST_STORAGE_BACKEND ?? "gnome_libsecret",
  encryptStringAsync: (value: string): Promise<Buffer> =>
    Promise.resolve(Buffer.from(`encrypted:${currentKey()}:${value}`, "utf8")),
  decryptStringAsync: (
    value: Buffer,
  ): Promise<{ result: string; shouldReEncrypt: boolean }> => {
    const stored = value.toString("utf8");
    const match = ENCRYPTED.exec(stored);
    if (!match) return Promise.reject(new Error("invalid encrypted value"));
    return Promise.resolve({
      result: stored.slice(match[0].length),
      shouldReEncrypt: match[1] !== currentKey(),
    });
  },
};
