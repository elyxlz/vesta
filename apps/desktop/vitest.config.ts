import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    alias: {
      // The sources under test import `app` from electron; the stub keeps a real
      // Electron runtime out of the unit tests.
      electron: path.resolve(__dirname, "test/electron-stub.ts"),
    },
  },
});
