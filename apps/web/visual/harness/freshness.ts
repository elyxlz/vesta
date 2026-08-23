import { fingerprintInputs } from "@vesta/visual/fingerprint";
import { appsRoot } from "@vesta/visual/platforms";
import path from "node:path";
import type { ScenarioInputs } from "../freshness-inputs.mjs";

export { scenarioInputs } from "../freshness-inputs.mjs";

// Vite serves source modules unbundled, so a coverage entry's URL names the
// file: `/src/x.tsx` under the web root, `/@fs/<abs>` for files outside it
// (core's sources). Pre-bundled dependencies and Vite's own client are not
// sources; the lockfile covers dependency changes.
export function coverageSourceFile(url: string): string | null {
  const webRoot = path.join(appsRoot, "web");
  let pathname: string;
  try {
    pathname = decodeURIComponent(new URL(url).pathname);
  } catch {
    return null;
  }
  if (
    pathname === "/" ||
    pathname.startsWith("/@vite/") ||
    pathname.startsWith("/@react-refresh")
  ) {
    return null;
  }
  const absolute = pathname.startsWith("/@fs/")
    ? pathname.slice("/@fs".length)
    : path.join(webRoot, pathname);
  if (absolute.includes(`${path.sep}node_modules${path.sep}`)) return null;
  const relative = path.relative(appsRoot, absolute);
  return relative.startsWith("..") ? null : relative;
}

export interface CoverageFunction {
  ranges: { startOffset: number; endOffset: number; count: number }[];
}

export interface CoverageEntry {
  url: string;
  source?: string;
  functions: CoverageFunction[];
}

// Vite's React plugin wraps every module in Fast Refresh plumbing whose
// callbacks run at load; those functions say nothing about the screen.
const REFRESH_MARKERS = ["RefreshRuntime", "$RefreshReg$", "$RefreshSig$"];

function isRefreshPlumbing(fn: CoverageFunction, source: string): boolean {
  const first = fn.ranges[0];
  if (!first) return false;
  const text = source.slice(first.startOffset, first.endOffset);
  return REFRESH_MARKERS.some((marker) => text.includes(marker));
}

// The router imports every page, so every module evaluates at load and
// module-level coverage would name the whole app for each screen. A module
// counts for a screen when a function past the script wrapper ran (a
// component rendered, a helper was called), or when it defines no function at
// all and is plain data that any consumer reads.
export function moduleExecuted(entry: CoverageEntry): boolean {
  const source = entry.source ?? "";
  const inner = entry.functions.filter((fn) => {
    const first = fn.ranges[0];
    const wrapper =
      first?.startOffset === 0 && first.endOffset === source.length;
    return !wrapper && !isRefreshPlumbing(fn, source);
  });
  if (inner.length === 0) return true;
  return inner.some((fn) => fn.ranges.some((range) => range.count > 0));
}

export function coverageSources(entries: readonly CoverageEntry[]): string[] {
  const files = new Set<string>();
  for (const entry of entries) {
    const file = coverageSourceFile(entry.url);
    if (file && moduleExecuted(entry)) files.add(file);
  }
  return [...files].sort();
}

export async function shotFingerprint(
  sources: readonly string[],
  inputs: ScenarioInputs,
): Promise<{ fingerprint: string; sources: string[] }> {
  return fingerprintInputs([...sources, ...inputs.files], inputs.extras);
}
