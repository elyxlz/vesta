import { describe, expect, it } from "vitest";

import {
  ApiError,
  compareReleaseVersions,
  createController,
  createReplica,
  readSse,
  rosterFromTree,
  sendMessage,
  seedTail,
} from "./index";

describe("@vesta/core barrel", () => {
  it("re-exports the runtime surface the apps import", () => {
    const runtime = [
      compareReleaseVersions,
      createController,
      createReplica,
      readSse,
      rosterFromTree,
      sendMessage,
      seedTail,
    ];
    for (const value of runtime) expect(value).toBeTypeOf("function");
    expect(ApiError).toBeTypeOf("function");
    expect(compareReleaseVersions("0.2.0", "0.1.0")).toBe(1);
  });
});
