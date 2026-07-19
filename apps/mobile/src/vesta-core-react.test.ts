import { describe, expect, it } from "vitest";

import { useReplica, useSyncState, useWatch } from "@vesta/core/react";

// Resolution gate for the `./react` subpath export of the file: dependency.
// Resolved config that makes this pass:
// - tsc: expo/tsconfig.base sets moduleResolution "bundler", which honors the
//   package `exports` map (no `paths` entry needed).
// - vitest 4: honors the `exports` map, so the subpath resolves with no alias.
// - metro: expo SDK 57 enables package exports by default
//   (resolver.unstable_enablePackageExports), so the same subpath resolves at
//   bundle time; validated by CI's mobile_native job, not this local gate.
describe("@vesta/core/react resolution", () => {
  it("resolves the react subpath export", () => {
    expect(typeof useReplica).toBe("function");
    expect(typeof useWatch).toBe("function");
    expect(typeof useSyncState).toBe("function");
  });
});
