import os from "node:os";

export const app = {
  getPath: (): string => process.env.VESTA_TEST_USER_DATA ?? os.tmpdir(),
};

const ENCRYPTION_PREFIX = "encrypted:";

export const safeStorage = {
  isEncryptionAvailable: (): boolean => true,
  encryptString: (value: string): Buffer =>
    Buffer.from(`${ENCRYPTION_PREFIX}${value}`, "utf8"),
  decryptString: (value: Buffer): string => {
    const stored = value.toString("utf8");
    if (!stored.startsWith(ENCRYPTION_PREFIX)) {
      throw new Error("invalid encrypted value");
    }
    return stored.slice(ENCRYPTION_PREFIX.length);
  },
};
