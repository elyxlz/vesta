import path from "node:path";
import { appsRoot } from "@vesta/visual/platforms";
import { describe, expect, it } from "vitest";
import {
  coverageSourceFile,
  coverageSources,
  moduleExecuted,
  type CoverageEntry,
} from "./freshness";

function entry(
  url: string,
  source: string,
  executed: [number, number, number][],
): CoverageEntry {
  return {
    url,
    source,
    functions: [
      {
        ranges: [{ startOffset: 0, endOffset: source.length, count: 1 }],
      },
      ...executed.map(([startOffset, endOffset, count]) => ({
        ranges: [{ startOffset, endOffset, count }],
      })),
    ],
  };
}

describe("coverageSourceFile", () => {
  it("maps vite's served urls to apps-relative files", () => {
    expect(
      coverageSourceFile("http://localhost:1430/src/pages/Home/index.tsx?t=1"),
    ).toBe("web/src/pages/Home/index.tsx");
    expect(
      coverageSourceFile(
        `http://localhost:1430/@fs${path.join(appsRoot, "core/src/index.ts")}`,
      ),
    ).toBe("core/src/index.ts");
    expect(
      coverageSourceFile("http://localhost:1430/@fs/elsewhere/file.ts"),
    ).toBeNull();
  });
  it("ignores vite's client, dependencies, and the document", () => {
    expect(coverageSourceFile("http://localhost:1430/@vite/client")).toBeNull();
    expect(
      coverageSourceFile(
        "http://localhost:1430/node_modules/.vite/deps/react.js",
      ),
    ).toBeNull();
    expect(coverageSourceFile("http://localhost:1430/")).toBeNull();
    expect(coverageSourceFile("not a url")).toBeNull();
  });
});

describe("moduleExecuted", () => {
  const source =
    "const a = 1; function render() { return a; } hot.then(() => RefreshRuntime.register());";
  const renderStart = source.indexOf("function render");
  const renderEnd = source.indexOf("}") + 1;
  const refreshStart = source.indexOf("() => RefreshRuntime");
  const refreshEnd = source.length - 2;

  it("counts a module whose own function ran", () => {
    expect(
      moduleExecuted(entry("u", source, [[renderStart, renderEnd, 3]])),
    ).toBe(true);
  });
  it("skips a module whose functions never ran", () => {
    expect(
      moduleExecuted(entry("u", source, [[renderStart, renderEnd, 0]])),
    ).toBe(false);
  });
  it("ignores fast refresh plumbing that runs on every load", () => {
    expect(
      moduleExecuted(
        entry("u", source, [
          [renderStart, renderEnd, 0],
          [refreshStart, refreshEnd, 1],
        ]),
      ),
    ).toBe(false);
  });
  it("counts a module that is plain data", () => {
    expect(moduleExecuted(entry("u", "export const X = 1;", []))).toBe(true);
  });
});

describe("coverageSources", () => {
  it("returns the sorted executed files", () => {
    const sources = coverageSources([
      entry("http://localhost:1430/src/b.ts", "export const b = 1;", []),
      entry("http://localhost:1430/src/a.ts", "export const a = 1;", []),
      entry("http://localhost:1430/@vite/client", "x", []),
    ]);
    expect(sources).toEqual(["web/src/a.ts", "web/src/b.ts"]);
  });
});
