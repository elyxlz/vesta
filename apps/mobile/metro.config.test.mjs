import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import metroConfig from "./metro.config.js";

const mobileRoot = path.dirname(fileURLToPath(import.meta.url));

describe("Metro monorepo resolution", () => {
  it("resolves dependencies imported by sibling @vesta/core from the mobile install", () => {
    expect(metroConfig.resolver.nodeModulesPaths).toContain(
      path.join(mobileRoot, "node_modules"),
    );
  });
});
