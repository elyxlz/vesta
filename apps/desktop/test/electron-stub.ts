import os from "node:os";
import path from "node:path";

// Stands in for the `electron` module under vitest (aliased in vitest.config.ts).
// store.ts resolves its path on every call, so a test points userData at its own
// temp dir through VESTA_TEST_USER_DATA.
export const app = {
  getPath: (name: string): string =>
    name === "temp"
      ? os.tmpdir()
      : (process.env.VESTA_TEST_USER_DATA ??
        path.join(os.tmpdir(), "vesta-test-userdata")),
};
