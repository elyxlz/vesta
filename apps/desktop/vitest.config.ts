import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["src/**/*.test.ts"],
    alias: { electron: path.resolve(__dirname, "test/electron-stub.ts") },
  },
});
