import { readdir, readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { appsRoot } from "@vesta/visual/platforms";

// What a mobile flow's shots depend on in the app: the modules reachable from
// the routes the flow deep-links into, plus the root layout every route renders
// through. The graph is Metro's own, built with the visual Metro config for the
// platform, so aliases, platform variants, and the harness substitutions
// resolve exactly as they do in the bundle.
const require = createRequire(import.meta.url);
// Expo CLI's internal modules resolve from the expo package, the way expo itself loads them,
// whichever node_modules the CLI landed in.
const expoRequire = createRequire(require.resolve("expo/package.json"));
const DEEP_LINK = /vesta-dev:\/\/([A-Za-z0-9/_\-[\].]*)/g;
const CAPTURE = /SCREENSHOT: ([a-z0-9-]+\.png)/g;

export function flowRoutes(flowText) {
  return [...new Set([...flowText.matchAll(DEEP_LINK)].map((m) => m[1]))];
}

export function flowShots(flowText) {
  return [...new Set([...flowText.matchAll(CAPTURE)].map((m) => m[1]))];
}

// Expo Router's file tree: a segment matches its own file or directory, a
// dynamic `[param]` one, or a `[...rest]` catch-all; an empty route is index.
// Every `_layout` along the way renders too, so it belongs to the route.
export async function routeFiles(appDirectory, route) {
  const segments = route.split("/").filter(Boolean);
  const files = await matchRouteFiles(appDirectory, segments);
  return [...new Set(files ?? (await layoutFiles(appDirectory)))];
}

async function layoutFiles(directory) {
  const layout = await findFile(directory, "_layout");
  if (!layout) return [];
  // Anchors stay visible beneath sheets and therefore contribute pixels too.
  const text = await readFile(layout, "utf8");
  const anchors = await Promise.all(
    [...text.matchAll(/\banchor:\s*["']([^"']+)["']/g)].map((match) =>
      findFile(directory, match[1]),
    ),
  );
  return [layout, ...anchors.filter(Boolean)];
}

async function matchRouteFiles(directory, segments) {
  const layouts = await layoutFiles(directory);
  if (segments.length === 0) {
    const index = await findFile(directory, "index");
    if (index) return [...layouts, index];
  }
  const entries = await readdir(directory, { withFileTypes: true });
  const segment = segments[0];
  const exact = entries.find(
    (entry) => entry.name.replace(/\.tsx?$/, "") === segment,
  );
  const groups = entries.filter(
    (entry) => entry.isDirectory() && /^\(.+\)$/.test(entry.name),
  );
  const dynamic = entries.find((entry) => /^\[[^.].*\]/.test(entry.name));
  const rest = entries.find((entry) => /^\[\.\.\./.test(entry.name));
  for (const entry of [exact, ...groups, dynamic, rest].filter(Boolean)) {
    const file = path.join(directory, entry.name);
    const group = groups.includes(entry);
    if (entry.isDirectory()) {
      const children = await matchRouteFiles(
        file,
        group ? segments : segments.slice(1),
      );
      if (children) return [...layouts, ...children];
    } else if (segment && (segments.length === 1 || entry === rest)) {
      return [...layouts, file];
    }
  }
  return null;
}

async function findFile(directory, stem) {
  const entries = await readdir(directory);
  const name = entries.find(
    (entry) => /\.tsx?$/.test(entry) && entry.replace(/\.tsx?$/, "") === stem,
  );
  return name ? path.join(directory, name) : null;
}

// Metro's dependency graph for the visual build of one platform: every module
// by absolute path with the absolute paths it imports. Loaded the way
// `expo export:embed` loads it, through Expo CLI's config loader (internal
// modules of the pinned @expo/cli), with the monorepo root watched so the
// shared node_modules resolve.
export async function metroModuleGraph(mobileRoot, metroConfigPath, platform) {
  const previousOverride = process.env.EXPO_OVERRIDE_METRO_CONFIG;
  process.env.EXPO_OVERRIDE_METRO_CONFIG = metroConfigPath;
  const Metro = require("metro");
  const MetroServer = require("metro/private/Server").default;
  const splitBundleOptions =
    require("metro/private/lib/splitBundleOptions").default;
  const { loadMetroConfigAsync } = expoRequire(
    "@expo/cli/build/src/start/server/metro/instantiateMetro",
  );
  const { getMetroDirectBundleOptionsForExpoConfig } = expoRequire(
    "@expo/cli/build/src/start/server/middleware/metroOptions",
  );
  const { getConfig } = require("@expo/config");
  const { exp } = getConfig(mobileRoot, { skipSDKVersionRequirement: true });
  let server;
  try {
    const { config } = await loadMetroConfigAsync(
      mobileRoot,
      { resetCache: false },
      {
        exp,
        isExporting: true,
        getMetroBundler: () => server.getBundler().getBundler(),
      },
    );
    server = await Metro.runMetro(
      { ...config, watchFolders: [...config.watchFolders, appsRoot] },
      { watch: false, waitForBundler: true },
    );
    const entryFile = require.resolve("expo-router/entry", {
      paths: [mobileRoot],
    });
    const direct = getMetroDirectBundleOptionsForExpoConfig(mobileRoot, exp, {
      splitChunks: false,
      mainModuleName: path.relative(mobileRoot, entryFile),
      platform,
      minify: false,
      mode: "production",
      engine: "hermes",
      isExporting: true,
      bytecode: false,
      hosted: false,
    });
    const { resolverOptions, transformOptions } = splitBundleOptions({
      ...MetroServer.DEFAULT_BUNDLE_OPTIONS,
      ...direct,
      entryFile,
      platform,
      dev: false,
      minify: false,
    });
    const graph = await server
      .getBundler()
      .buildGraphForEntries([entryFile], transformOptions, resolverOptions);
    const edges = new Map();
    for (const [file, module] of graph.dependencies) {
      edges.set(
        file,
        [...module.dependencies.values()].map(
          (dependency) => dependency.absolutePath,
        ),
      );
    }
    return edges;
  } finally {
    if (server) await server.end();
    if (previousOverride === undefined)
      delete process.env.EXPO_OVERRIDE_METRO_CONFIG;
    else process.env.EXPO_OVERRIDE_METRO_CONFIG = previousOverride;
  }
}

// The transitive closure of the roots in the graph, kept to sources under
// apps/ outside node_modules (the lockfile stands for dependencies).
export function sourceClosure(graph, roots) {
  const seen = new Set();
  const stack = [...roots];
  while (stack.length > 0) {
    const file = stack.pop();
    if (seen.has(file)) continue;
    seen.add(file);
    for (const dependency of graph.get(file) ?? []) stack.push(dependency);
  }
  return [...seen]
    .filter(
      (file) =>
        file.startsWith(`${appsRoot}${path.sep}`) &&
        !file.includes(`${path.sep}node_modules${path.sep}`),
    )
    .map((file) => path.relative(appsRoot, file))
    .sort();
}

export async function flowSources(flowPath, appDirectory, graph) {
  const text = await readFile(flowPath, "utf8");
  const roots = new Set();
  for (const route of flowRoutes(text)) {
    for (const file of await routeFiles(appDirectory, route)) roots.add(file);
  }
  return { shots: flowShots(text), sources: sourceClosure(graph, [...roots]) };
}
