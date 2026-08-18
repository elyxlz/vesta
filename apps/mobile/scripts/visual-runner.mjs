// Mobile-shared runner helpers: process spawning, fingerprints, the harness
// boundary check, and Maestro result parsing. Both mobile runners import from
// here; neither imports from the other for these.
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { createHash } from "node:crypto";
import { access, readFile, readdir, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { themedSibling } from "@vesta/visual/platforms";
import { atomicWriteFile } from "@vesta/visual/store";

export { atomicWriteFile };

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
export const mobileRoot = path.resolve(scriptDirectory, "..");
export const repositoryRoot = path.resolve(mobileRoot, "../..");
export const visualDirectory = path.join(mobileRoot, ".visual");
export const nativeAnimationHookPath = path.join(
  mobileRoot,
  "visual/harness/disable-ios-animations.swift",
);

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
    path.join(repositoryRoot, "package.json"),
    path.join(repositoryRoot, "package-lock.json"),
    path.join(mobileRoot, "plugins"),
    path.join(mobileRoot, "modules"),
    path.join(mobileRoot, "src/theme/native-config.generated.json"),
    path.join(mobileRoot, "assets/app-icon-dev.png"),
    path.join(mobileRoot, "assets/blank-splash.xml"),
    nativeAnimationHookPath,
  ];
}

export async function nativeInputFingerprint() {
  return fingerprintPaths(nativeInputTargets());
}

// The JavaScript bundle's inputs: when their fingerprint matches the one recorded at the last
// successful install for a target, the export/install phase is skipped and a scan goes straight
// to its flows. Flow and fixture edits count (the harness ships in the bundle); Maestro yml does
// not, since it never enters the bundle.
function jsInputTargets() {
  return [
    path.join(mobileRoot, "app"),
    path.join(mobileRoot, "src"),
    path.join(mobileRoot, "visual"),
    path.join(mobileRoot, "assets"),
    path.join(mobileRoot, "app.config.ts"),
    path.join(mobileRoot, "package.json"),
    path.join(repositoryRoot, "package-lock.json"),
  ];
}

export async function jsInputFingerprint() {
  return fingerprintPaths(jsInputTargets());
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

export function createInactivityWatchdog(onTimeout, timeoutMs) {
  let timer;
  const cancel = () => {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
  };
  const reset = () => {
    cancel();
    timer = setTimeout(() => {
      timer = undefined;
      onTimeout();
    }, timeoutMs);
  };
  reset();
  return { cancel, reset };
}


// A shot is settled when two framebuffer grabs in a row are byte-identical.
// The OS appearance flip re-renders the app with no signal a runner can await,
// so stability of the picture itself is the signal, bounded by the budget.
export const SETTLE_POLL_MS = 120;
export const SETTLE_TIMEOUT_MS = 8_000;

export async function grabUntilStable(grab, options = {}) {
  const pollMs = options.pollMs ?? SETTLE_POLL_MS;
  const timeoutMs = options.timeoutMs ?? SETTLE_TIMEOUT_MS;
  const deadline = Date.now() + timeoutMs;
  let previous = await grab();
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, pollMs));
    const current = await grab();
    if (current.equals(previous)) return current;
    previous = current;
  }
  return previous;
}

// One drive, both themes: shoot the light platform now, flip the OS appearance,
// shoot the dark sibling once the picture settles, then flip back and wait for
// the light picture to settle so the flow continues where it was.
export async function captureBothThemes({ platform, name, grab, setDark, store }) {
  await store(platform, name, await grab());
  const dark = themedSibling(platform, "dark");
  if (!dark) return;
  await setDark(true);
  await store(dark, name, await grabUntilStable(grab));
  await setDark(false);
  await grabUntilStable(grab);
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
// names, seen names, the inactivity watchdog); the platform supplies capture(),
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
      await handlers.capture(target, screenshot);
      cycle.seen.add(screenshot);
      response.writeHead(204).end();
      if ([...cycle.expected].every((name) => cycle.seen.has(name))) {
        cycle.completed = true;
        cycle.watchdog.cancel();
        cycle.resolve();
      } else {
        cycle.watchdog.reset();
      }
    } catch (error) {
      response.writeHead(500).end(error.message);
      if (cycle && !cycle.completed) {
        cycle.completed = true;
        cycle.watchdog.cancel();
        cycle.reject(error);
      }
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
    urls: targets.map((_target, index) => `${baseUrl}/__visual_capture/${index + 1}`),
    async beginCycle(manifest, timeoutMs = 120_000) {
      if (cycle && !cycle.completed) {
        throw new Error("A screenshot cycle is already active.");
      }
      const expected = new Set(manifest.scenarios.map((scenario) => scenario.screenshot));
      let resolveCycle;
      let rejectCycle;
      const completion = new Promise((resolve, reject) => {
        resolveCycle = resolve;
        rejectCycle = reject;
      });
      cycle = {
        completed: false,
        expected,
        seen: new Set(),
        resolve: resolveCycle,
        reject: rejectCycle,
        watchdog: null,
      };
      cycle.watchdog = createInactivityWatchdog(() => {
        if (cycle.completed) return;
        cycle.completed = true;
        cycle.reject(
          new Error(
            `Timed out waiting for screenshots: ${[...expected]
              .filter((screenshot) => !cycle.seen.has(screenshot))
              .join(", ")}`,
          ),
        );
      }, timeoutMs);
      const startedCycle = cycle;
      return {
        completion,
        seen: startedCycle.seen,
        settle() {
          if (startedCycle.completed) return;
          startedCycle.completed = true;
          startedCycle.watchdog.cancel();
          startedCycle.resolve();
        },
      };
    },
    fail(error) {
      if (!cycle || cycle.completed) return;
      cycle.completed = true;
      cycle.watchdog.cancel();
      cycle.reject(error);
    },
    async close() {
      if (cycle && !cycle.completed) {
        cycle.completed = true;
        cycle.watchdog.cancel();
        cycle.reject(new Error("Screenshot bridge stopped."));
      }
      await new Promise((resolve) => server.close(resolve));
      if (handlers.close) await handlers.close();
    },
  };
}
