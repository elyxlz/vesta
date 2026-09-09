// Mobile-shared runner helpers: process spawning, fingerprints, the harness
// boundary check, and Maestro result parsing. Both mobile runners import from
// here; neither imports from the other.
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { createHash } from "node:crypto";
import { access, readFile, readdir, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { createFingerprinter, staleReasons } from "@vesta/visual/fingerprint";
import { themedSibling } from "@vesta/visual/platforms";
import { scenariosForPlatform } from "@vesta/visual/registry";
import { selectRegistry } from "@vesta/visual/selection";
import { grabUntilStable } from "@vesta/visual/stability";
import {
  atomicWriteFile,
  putShotRecord,
  readShotRecord,
  shotIsFresh,
} from "@vesta/visual/store";
import { flowSources, metroModuleGraph } from "./visual-sources.mjs";

export { atomicWriteFile, grabUntilStable };

// Maestro executes whole flows, even when a gallery refresh selects one card.
// Keep the platform catalog beside the selection so every sibling capture is
// planned and recorded, without widening which flows the user asked to run.
export function selectMobileRegistry(registry, platform, selection) {
  const catalogScenarios = scenariosForPlatform(registry, platform);
  return {
    ...selectRegistry({ ...registry, scenarios: catalogScenarios }, selection),
    catalogScenarios,
  };
}

export function scenariosInSelectedFlow(manifest, shots) {
  const requested = new Set(manifest.scenarios.map((s) => s.screenshot));
  if (!shots.some((shot) => requested.has(shot))) return [];
  const names = new Set(shots);
  return (manifest.catalogScenarios ?? manifest.scenarios).filter((s) =>
    names.has(s.screenshot),
  );
}

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
export const mobileRoot = path.resolve(scriptDirectory, "..");
// The npm workspace root: its lockfile is the one that pins every dependency.
export const appsRoot = path.resolve(mobileRoot, "..");
export const repositoryRoot = path.resolve(mobileRoot, "../..");
export const visualDirectory = path.join(mobileRoot, ".visual");
export const nativeAnimationHookPath = path.join(
  mobileRoot,
  "visual/harness/disable-ios-animations.swift",
);
// The Metro config both runners bundle the harness with.
export const metroConfigPath = path.join(mobileRoot, "visual/metro.config.js");

const shardCount = 2;
// Gentle mode trades wall time for machine responsiveness: one simulator shard instead of two,
// and every child process (build, bundler, Maestro, emulator) runs at utility QoS so the capture
// never competes with foreground work. One-shot commands only; watch mode keeps both shards.
let gentleMode = false;
export function setGentleMode(enabled) {
  gentleMode = enabled;
}
export function activeShardCount() {
  return gentleMode ? 1 : shardCount;
}
export function gentleSpawnPlan(command, argumentsList, gentle, platform) {
  if (!gentle || platform !== "darwin") return { command, argumentsList };
  return {
    command: "taskpolicy",
    argumentsList: ["-c", "utility", command, ...argumentsList],
  };
}

export function run(command, argumentsList, options = {}) {
  const shown = [command, ...argumentsList]
    .map((value) => (value.includes(" ") ? JSON.stringify(value) : value))
    .join(" ");
  if (!options.quiet) console.log(`\n› ${shown}`);
  const plan = gentleSpawnPlan(
    command,
    argumentsList,
    gentleMode,
    process.platform,
  );
  return new Promise((resolve, reject) => {
    const child = spawn(plan.command, plan.argumentsList, {
      cwd: options.cwd ?? mobileRoot,
      env: { ...process.env, ...options.env },
      stdio:
        options.capture || options.tee ? ["ignore", "pipe", "pipe"] : "inherit",
    });
    let stdout = "";
    let stderr = "";
    if (options.capture || options.tee) {
      child.stdout.on("data", (chunk) => {
        stdout += chunk;
        if (options.tee) process.stdout.write(chunk);
      });
      child.stderr.on("data", (chunk) => {
        stderr += chunk;
        if (options.tee) process.stderr.write(chunk);
      });
    }
    child.on("error", reject);
    child.on("exit", (code, signal) => {
      if (code === 0 || options.allowFailure) {
        resolve({ code, signal, stdout, stderr });
        return;
      }
      const detail = options.capture
        ? [stdout.trim(), stderr.trim()].filter(Boolean).join("\n")
        : "";
      const failure = new Error(
        `${command} exited with ${code ?? signal}.${detail ? `\n${detail}` : ""}`,
      );
      failure.stdout = stdout;
      failure.stderr = stderr;
      reject(failure);
    });
  });
}

// Maestro prints one result line per flow; fold them into pass/fail lists so a failed run's
// status names the failing flows instead of a bare exit code.
export function maestroFlowSummary(output) {
  const passed = [];
  const failed = [];
  const resultLine =
    /\[(Passed|Failed)\]\s+(.+?)\s+\((?:\d+h\s*)?(?:\d+m\s*)?\d+s\)(?:\s+\((.+)\))?\s*$/;
  for (const line of output.split("\n")) {
    const match = resultLine.exec(line);
    if (!match) continue;
    if (match[1] === "Passed") passed.push(match[2]);
    else failed.push({ name: match[2], reason: match[3] ?? "" });
  }
  return { passed, failed };
}

export function flowFailureError(error) {
  const summary = maestroFlowSummary(
    `${error.stdout ?? ""}\n${error.stderr ?? ""}`,
  );
  if (summary.failed.length === 0) return error;
  const names = summary.failed
    .map((flow) => (flow.reason ? `${flow.name} (${flow.reason})` : flow.name))
    .join("; ");
  return new Error(
    `${summary.failed.length} of ${
      summary.passed.length + summary.failed.length
    } flows failed: ${names}`,
  );
}

export async function exists(target) {
  try {
    await access(target);
    return true;
  } catch {
    return false;
  }
}

async function fingerprintPaths(targets, shouldInclude = () => true) {
  const files = [];
  for (const target of targets) {
    if (!(await exists(target))) continue;
    const info = await stat(target);
    if (info.isDirectory()) files.push(...(await filesBelow(target)));
    if (info.isFile()) files.push(target);
  }
  const uniqueFiles = [...new Set(files)]
    .filter(shouldInclude)
    .sort((left, right) => left.localeCompare(right));
  const hash = createHash("sha256");
  for (const file of uniqueFiles) {
    hash.update(path.relative(repositoryRoot, file));
    hash.update("\0");
    hash.update(await readFile(file));
    hash.update("\0");
  }
  return hash.digest("hex");
}

function nativeInputTargets() {
  return [
    path.join(mobileRoot, "app.config.ts"),
    path.join(mobileRoot, "package.json"),
    path.join(appsRoot, "package.json"),
    path.join(appsRoot, "package-lock.json"),
    path.join(mobileRoot, "plugins"),
    path.join(mobileRoot, "modules"),
    path.join(mobileRoot, "src/theme/native-config.generated.json"),
    path.join(mobileRoot, "assets/app-icon-dev.png"),
    path.join(mobileRoot, "assets/blank-splash.xml"),
    nativeAnimationHookPath,
  ];
}

// Gradle and Xcode write their outputs inside modules/*/android|ios, so a
// build would churn the fingerprint of inputs that did not change.
const NATIVE_OUTPUT_SEGMENTS = ["build", ".cxx", ".gradle", "DerivedData"];

export function isNativeSource(file) {
  return !file
    .split(path.sep)
    .some((segment) => NATIVE_OUTPUT_SEGMENTS.includes(segment));
}

export async function nativeInputFingerprint() {
  return fingerprintPaths(nativeInputTargets(), isNativeSource);
}

// The JavaScript bundle's inputs: when their fingerprint matches the one recorded at the last
// successful install for a target, the export/install phase is skipped and a scan goes straight
// to its flows. Flow and fixture edits count (the harness ships in the bundle), and so does
// @vesta/core, which the bundle carries from source; Maestro yml does not, since it never
// enters the bundle.
function jsInputTargets() {
  return [
    path.join(mobileRoot, "app"),
    path.join(mobileRoot, "src"),
    path.join(mobileRoot, "visual"),
    path.join(mobileRoot, "assets"),
    path.join(mobileRoot, "app.config.ts"),
    path.join(mobileRoot, "package.json"),
    path.join(appsRoot, "core/src"),
    path.join(appsRoot, "core/package.json"),
    path.join(appsRoot, "package-lock.json"),
  ];
}

export async function jsInputFingerprint() {
  return fingerprintPaths(jsInputTargets(), isJsBundleInput);
}

export function isJsBundleInput(file) {
  return (
    path.extname(file) !== ".md" &&
    !file.split(path.sep).includes(".agents") &&
    file !== path.join(mobileRoot, "visual/scenarios.json")
  );
}

export function jsFingerprintPath(target) {
  return path.join(visualDirectory, `js-fingerprint-${target}.txt`);
}

export async function jsBundleCurrent(target) {
  try {
    const stored = await readFile(jsFingerprintPath(target), "utf8");
    return stored === (await jsInputFingerprint());
  } catch {
    return false;
  }
}

export async function recordJsBundle(target) {
  await atomicWriteFile(jsFingerprintPath(target), await jsInputFingerprint());
}

export async function filesBelow(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await filesBelow(target)));
    if (entry.isFile()) files.push(target);
  }
  return files;
}

export async function assertHarnessBoundary() {
  const applicationFiles = [
    ...(await filesBelow(path.join(mobileRoot, "app"))),
    ...(await filesBelow(path.join(mobileRoot, "src"))),
  ].filter((file) => [".ts", ".tsx"].includes(path.extname(file)));
  const forbiddenMarkers = [
    "isVisualCapture",
    "VESTA_MAESTRO_HARNESS",
    "/visual/harness",
  ];
  const violations = [];

  for (const file of applicationFiles) {
    const source = await readFile(file, "utf8");
    if (forbiddenMarkers.some((marker) => source.includes(marker))) {
      violations.push(path.relative(mobileRoot, file));
    }
  }
  if (violations.length > 0) {
    throw new Error(
      `Capture harness logic must stay outside app/ and src/: ${violations.join(", ")}`,
    );
  }
}

// One drive, both themes: shoot the light platform now, flip the OS appearance,
// shoot the dark sibling once the picture settles, then flip back and wait for
// the light picture to settle so the flow continues where it was.
// Both themes of one shot, then its freshness record when the plan carries one.
export async function captureBothThemes({
  platform,
  name,
  grab,
  setDark,
  store,
  record,
  light,
}) {
  await store(platform, name, light ?? (await grabUntilStable(grab)));
  const dark = themedSibling(platform, "dark");
  if (dark) {
    try {
      await setDark(true);
      await store(dark, name, await grabUntilStable(grab));
    } finally {
      await setDark(false);
      await grabUntilStable(grab);
    }
  }
  if (record) await putShotRecord(platform, name, record);
}

// A page is complete only when a further scroll produces the same stable
// framebuffer. No labels, card count, or knowledge of the page's contents.
export function createPageCapture() {
  const pages = new Map();
  return async (options, step) => {
    if (step === undefined) return captureBothThemes(options);
    if (!["start", "next"].includes(step))
      throw new Error(`Invalid page capture step: ${step}`);
    const key = `${options.platform}/${options.name}`;
    if (step === "start") pages.set(key, { parts: [], previous: null });
    const page = pages.get(key);
    if (!page) throw new Error("Page capture has not started");
    const light = await grabUntilStable(options.grab);
    if (page.previous?.equals(light)) {
      if (options.record)
        await putShotRecord(options.platform, options.name, {
          ...options.record,
          parts: page.parts,
        });
      pages.delete(key);
      return { more: false };
    }
    if (page.parts.length >= 24)
      throw new Error("Page exceeded 24 viewports; capture is incomplete");
    const name =
      page.parts.length === 0
        ? options.name
        : options.name.replace(
            /\.png$/,
            `--${String(page.parts.length + 1).padStart(2, "0")}.png`,
          );
    await captureBothThemes({ ...options, name, record: undefined, light });
    page.previous = light;
    page.parts.push(name);
    return { more: true };
  };
}

// Which flows a scan must run: a flow is fresh, and skipped, when every shot it
// takes on this platform exists in both themes with the fingerprint of the
// flow's current inputs (the sources reachable from its routes in Metro's
// graph, the flow text, the capture mechanics, the native inputs, its cards).
// `captureAll` retakes everything. The plan carries each shot's record so the
// bridge writes it beside the shot it takes.
export async function planFlows(manifest, options) {
  const { platform, metroPlatform, mechanics, extras, captureAll } = options;
  const fingerprint = createFingerprinter();
  const graph = await metroModuleGraph(
    mobileRoot,
    metroConfigPath,
    metroPlatform,
  );
  const appDirectory = path.join(mobileRoot, "app");
  const catalog = manifest.catalogScenarios ?? manifest.scenarios;
  const platforms = [platform, themedSibling(platform, "dark")].filter(Boolean);
  const records = new Map();
  const runShots = new Set();
  const flows = [];
  const skipped = [];
  const units = [];
  for (const flow of manifest.flows) {
    const flowPath = path.resolve(mobileRoot, flow);
    const { shots, sources } = await flowSources(flowPath, appDirectory, graph);
    const flowScenarios = scenariosInSelectedFlow(manifest, shots);
    const expected = flowScenarios.map((scenario) => scenario.screenshot);
    if (expected.length === 0) continue;
    const cards = flowScenarios.map((scenario) => JSON.stringify(scenario));
    const record = await fingerprint(
      [
        ...sources,
        flowPath,
        path.join(mobileRoot, "maestro/visual/wait-for-launch.yml"),
        path.join(mobileRoot, "maestro/visual/capture-page.yml"),
        path.join(mobileRoot, "maestro/visual/prepare-page.yml"),
        ...mechanics,
        path.join(appsRoot, "visual/stability.mjs"),
        path.join(appsRoot, "visual/platforms.mjs"),
      ],
      [...extras, ...cards],
    );
    // Why the flow is stale: shots never recorded, and the files that moved
    // since the last record (read from the first shot that has one).
    const missing = [];
    let previous = null;
    let stale = captureAll;
    for (const shot of expected) {
      const recorded = await readShotRecord(platform, shot);
      if (!recorded) missing.push(shot);
      previous ??= recorded;
      if (!(await shotIsFresh(platforms, shot, record.fingerprint)))
        stale = true;
    }
    const fresh = !stale;
    units.push({
      name: path.basename(flow),
      shots: expected,
      stale,
      reasons: stale
        ? { ...staleReasons(previous ?? {}, record), missing }
        : null,
    });
    if (fresh) {
      skipped.push(flow);
      continue;
    }
    flows.push(flow);
    for (const shot of expected) {
      records.set(shot, record);
      runShots.add(shot);
    }
  }
  const scenarios = catalog.filter((scenario) =>
    runShots.has(scenario.screenshot),
  );
  return { flows, skipped, records, scenarios, units };
}

// The plan as the gallery shows it before a scan: one line of JSON on stdout.
export function printPlan(runner, plan) {
  process.stdout.write(`${JSON.stringify({ runner, units: plan.units })}\n`);
}

async function readRequestJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 4096) throw new Error("Screenshot request is too large.");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

// The screenshot bridge Maestro's runScript callback POSTs to, one route per
// target (a simulator or an emulator). It owns the cycle bookkeeping (expected
// names, seen names); the platform supplies capture(),
// an optional action() for host-side gestures, and an optional close().
export async function startScreenshotBridge(targets, handlers) {
  let cycle;
  const routes = new Map(
    targets.map((target, index) => [`/__visual_capture/${index + 1}`, target]),
  );
  const server = createServer(async (request, response) => {
    const pathname = new URL(request.url ?? "/", "http://127.0.0.1").pathname;
    const target = routes.get(pathname);
    if (request.method !== "POST" || !target) {
      response.writeHead(404).end("Not found");
      return;
    }
    try {
      const payload = await readRequestJson(request);
      if (typeof payload.action === "string") {
        if (handlers.action) await handlers.action(target, payload.action);
        response.writeHead(204).end();
        return;
      }
      if (!cycle) {
        response.writeHead(204).end();
        return;
      }
      if (cycle.completed) throw new Error("No screenshot cycle is active.");
      const screenshot = payload.screenshot;
      if (
        typeof screenshot !== "string" ||
        path.basename(screenshot) !== screenshot ||
        !screenshot.endsWith(".png")
      ) {
        throw new Error(`Invalid screenshot name: ${screenshot}`);
      }
      if (!cycle.expected.has(screenshot))
        throw new Error(`Unexpected screenshot: ${screenshot}`);
      const result = await handlers.capture(
        target,
        screenshot,
        payload.pageStep,
      );
      if (!result?.more) cycle.seen.add(screenshot);
      response
        .writeHead(200, { "Content-Type": "application/json" })
        .end(JSON.stringify(result ?? {}));
      if ([...cycle.expected].every((name) => cycle.seen.has(name))) {
        cycle.completed = true;
        cycle.resolve();
      }
    } catch (error) {
      // The failing flow reports the message; the cycle stays open so every
      // other flow's shots still land.
      response.writeHead(500).end(error.message);
    }
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    server.close();
    throw new Error("Could not start the local screenshot bridge.");
  }
  const baseUrl = `http://127.0.0.1:${address.port}`;

  return {
    urls: targets.map(
      (_target, index) => `${baseUrl}/__visual_capture/${index + 1}`,
    ),
    async beginCycle(manifest) {
      if (cycle && !cycle.completed) {
        throw new Error("A screenshot cycle is already active.");
      }
      const expected = new Set(
        manifest.scenarios.map((scenario) => scenario.screenshot),
      );
      let resolveCycle;
      let rejectCycle;
      const completion = new Promise((resolve, reject) => {
        resolveCycle = resolve;
        rejectCycle = reject;
      });
      // The runner awaits completion only after Maestro exits, so a rejection
      // before then (a failed capture) must not surface as an unhandled rejection.
      completion.catch(() => {});
      cycle = {
        completed: false,
        expected,
        seen: new Set(),
        resolve: resolveCycle,
        reject: rejectCycle,
      };
      const startedCycle = cycle;
      return {
        completion,
        seen: startedCycle.seen,
        settle() {
          if (startedCycle.completed) return;
          startedCycle.completed = true;
          startedCycle.resolve();
        },
      };
    },
    fail(error) {
      if (!cycle || cycle.completed) return;
      cycle.completed = true;
      cycle.reject(error);
    },
    async close() {
      if (cycle && !cycle.completed) {
        cycle.completed = true;
        cycle.reject(new Error("Screenshot bridge stopped."));
      }
      await new Promise((resolve) => server.close(resolve));
      if (handlers.close) await handlers.close();
    },
  };
}
