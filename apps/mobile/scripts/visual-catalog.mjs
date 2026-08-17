#!/usr/bin/env node

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import {
  closeSync,
  existsSync,
  openSync,
  statSync,
  watch as watchPath,
} from "node:fs";
import { createServer } from "node:http";
import {
  access,
  copyFile,
  mkdir,
  readFile,
  readdir,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { fileURLToPath } from "node:url";
import os from "node:os";
import path from "node:path";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const mobileRoot = path.resolve(scriptDirectory, "..");
const repositoryRoot = path.resolve(mobileRoot, "../..");
const visualDirectory = path.join(mobileRoot, ".visual");
export const androidVisualDirectory = path.join(visualDirectory, "android");
// The Android runner captures one variant per run: the same build and flows on a different
// emulator persona. The galaxy variant runs classic 3-button navigation, so every screen is
// exercised with a visible bottom navigation bar and its status bar insets.
export const androidVariants = {
  android: {
    avd: "vesta-visual",
    label: "Android",
    navOverlay: "com.android.internal.systemui.navbar.gestural",
  },
  "android-galaxy": {
    avd: "vesta-visual-galaxy",
    label: "Android \u00b7 3-button",
    navOverlay: "com.android.internal.systemui.navbar.threebutton",
  },
};
export function androidWorkDirectory(variant) {
  return variant === "android"
    ? androidVisualDirectory
    : path.join(visualDirectory, variant);
}
export function androidMaestroDirectoryOf(variant) {
  return path.join(androidWorkDirectory(variant), "maestro");
}
export function platformShotsDirectory(platform) {
  return path.join(shotsDirectory, platform);
}
export const androidMaestroDirectory = path.join(
  androidVisualDirectory,
  "maestro",
);
// The shots registry on disk: one PNG per scenario per platform, replaced in
// place as each scan captures it. A failed or partial run leaves the entries
// it did not reach untouched.
const shotsDirectory = path.join(visualDirectory, "shots");
const iosShotsDirectory = path.join(shotsDirectory, "ios");
export const androidShotsDirectory = path.join(shotsDirectory, "android");
const maestroDirectory = path.join(visualDirectory, "maestro");
const derivedDataDirectory = path.join(visualDirectory, "derived-data");
const bundleDirectory = path.join(visualDirectory, "bundle");
const nativeIosDirectory = path.join(visualDirectory, "native/ios");
const nativeFingerprintPath = path.join(
  visualDirectory,
  "native/fingerprint.txt",
);
const nativeTransactionDirectory = path.join(
  mobileRoot,
  ".expo/visual-native-transaction",
);
const nativeTransactionStatePath = path.join(
  nativeTransactionDirectory,
  "state.json",
);
const watchFlowsDirectory = path.join(visualDirectory, "watch/flows");
const manifestPath = path.join(mobileRoot, "visual/scenarios.json");
const metroConfigPath = path.join(mobileRoot, "visual/metro.config.js");
const nativeAnimationHookPath = path.join(
  mobileRoot,
  "visual/harness/disable-ios-animations.swift",
);
const expoRouterEntryPath = path.resolve(
  mobileRoot,
  "../node_modules/expo-router/entry.js",
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
// The initial state carries the epoch, not boot time: a restarted server must not outrank the
// last phase an in-flight capture wrote to the run-status file.
let visualCatalogStatus = {
  state: "ready",
  message: "Screenshots are up to date",
  detail: "",
  startedAt: null,
  updatedAt: new Date(0).toISOString(),
};

const mimeTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
]);

function setVisualCatalogStatus(state, options = {}) {
  visualCatalogStatus = {
    state,
    message: options.message ?? "",
    detail: options.detail ?? "",
    startedAt: options.startedAt ?? null,
    platform: options.platform ?? null,
    updatedAt: new Date().toISOString(),
  };
}

// One-shot captures run in a separate process from a gallery server, so their progress crosses
// over on disk: the capture writes each phase to this file and /status.json serves whichever of
// the server's own state and the file is newer. A "capturing" file entry a hard-killed run left
// behind goes stale after the cutoff instead of showing a phantom run forever.
const runStatusPath = path.join(visualDirectory, "run-status.json");
const STALE_CAPTURING_MS = 45 * 60 * 1000;

export async function publishRunStatus(state, options = {}) {
  setVisualCatalogStatus(state, options);
  await mkdir(visualDirectory, { recursive: true });
  await atomicWriteFile(
    runStatusPath,
    `${JSON.stringify(visualCatalogStatus)}\n`,
  );
}

export function newerRunStatus(serverStatus, fileStatus, now) {
  if (!fileStatus?.updatedAt) return serverStatus;
  if (
    fileStatus.state === "capturing" &&
    now - Date.parse(fileStatus.updatedAt) > STALE_CAPTURING_MS
  ) {
    return serverStatus;
  }
  return fileStatus.updatedAt > serverStatus.updatedAt
    ? fileStatus
    : serverStatus;
}

async function currentRunStatus() {
  let fileStatus = null;
  try {
    fileStatus = JSON.parse(await readFile(runStatusPath, "utf8"));
  } catch {
    fileStatus = null;
  }
  return newerRunStatus(visualCatalogStatus, fileStatus, Date.now());
}

class CaptureSupersededError extends Error {
  constructor(detail = "") {
    super(detail ? `Superseded by ${detail}` : "Superseded by newer edits");
    this.name = "CaptureSupersededError";
  }
}

function usage() {
  console.log(`Usage:
  npm run visual:ios -- [options]
  npm run visual:serve -- [options]

Commands:
  capture       Build, capture screenshots, and serve the gallery (default)
  serve         Serve the gallery from the registry and existing shots
  watch         Capture, watch code, and recapture after edits

Options:
  --device <name-or-udid>  Simulator to use
  --show-simulator         Open Simulator.app while capturing
  --skip-build             Skip even the fast JavaScript rebundle
  --clean-native           Regenerate the cached native iOS project
  --gentle                 One simulator shard at utility QoS: slower, but the
                           machine stays responsive (capture only)
  --no-serve               Capture without starting the gallery server
  --no-open                Do not open the gallery in a browser
  --port <number>          Gallery port (default: 4173)
  --help                   Show this help
`);
}

function parseArguments(values) {
  const argumentsCopy = [...values];
  const command =
    argumentsCopy[0] && !argumentsCopy[0].startsWith("-")
      ? argumentsCopy.shift()
      : "capture";
  const options = {
    command,
    device: "",
    showSimulator: false,
    skipBuild: false,
    cleanNative: false,
    gentle: false,
    serve: true,
    open: true,
    port: 4173,
  };

  for (let index = 0; index < argumentsCopy.length; index += 1) {
    const argument = argumentsCopy[index];
    if (argument === "--help") {
      usage();
      process.exit(0);
    }
    if (argument === "--skip-build") {
      options.skipBuild = true;
      continue;
    }
    if (argument === "--show-simulator") {
      options.showSimulator = true;
      continue;
    }
    if (argument === "--clean-native") {
      options.cleanNative = true;
      continue;
    }
    if (argument === "--gentle") {
      options.gentle = true;
      continue;
    }
    if (argument === "--no-serve") {
      options.serve = false;
      continue;
    }
    if (argument === "--no-open") {
      options.open = false;
      continue;
    }
    if (argument === "--device" || argument === "--port") {
      const value = argumentsCopy[index + 1];
      if (!value) throw new Error(`${argument} requires a value.`);
      index += 1;
      if (argument === "--device") options.device = value;
      if (argument === "--port") {
        const port = Number(value);
        if (!Number.isInteger(port) || port < 1 || port > 65_535) {
          throw new Error(`Invalid port: ${value}`);
        }
        options.port = port;
      }
      continue;
    }
    throw new Error(`Unknown argument: ${argument}`);
  }

  if (!["capture", "serve", "watch"].includes(command)) {
    throw new Error(`Unknown command: ${command}`);
  }
  if (options.skipBuild && options.cleanNative) {
    throw new Error("--skip-build and --clean-native cannot be used together.");
  }
  if (options.gentle && command === "watch") {
    throw new Error("--gentle only applies to one-shot capture commands.");
  }
  return options;
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

let temporaryFileCounter = 0;

export async function atomicWriteFile(target, contents) {
  await mkdir(path.dirname(target), { recursive: true });
  temporaryFileCounter += 1;
  const temporary = `${target}.${process.pid}.${temporaryFileCounter}.tmp`;
  await writeFile(temporary, contents);
  await rename(temporary, target);
}

async function writeFileIfChanged(target, contents) {
  if ((await exists(target)) && (await readFile(target, "utf8")) === contents) {
    return false;
  }
  await atomicWriteFile(target, contents);
  return true;
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

const scenarioPlatforms = ["ios", "android"];

export function scenarioOnPlatform(scenario, platform) {
  const family = platform.startsWith("android") ? "android" : platform;
  return !Array.isArray(scenario.platforms) ||
    scenario.platforms.includes(family);
}

export async function loadManifest(platform = "ios") {
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  if (manifest.version !== 1) {
    throw new Error(`Unsupported visual manifest version: ${manifest.version}`);
  }
  if (typeof manifest.appId !== "string" || !manifest.appId) {
    throw new Error("The visual manifest must define appId.");
  }
  if (!Array.isArray(manifest.flows) || manifest.flows.length === 0) {
    throw new Error("The visual manifest must define at least one flow.");
  }
  if (!Array.isArray(manifest.scenarios) || manifest.scenarios.length === 0) {
    throw new Error("The visual manifest must define at least one scenario.");
  }

  const ids = new Set();
  const screenshots = new Set();
  for (const scenario of manifest.scenarios) {
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(scenario.id ?? "")) {
      throw new Error(`Invalid visual scenario id: ${scenario.id}`);
    }
    if (ids.has(scenario.id)) {
      throw new Error(`Duplicate visual scenario id: ${scenario.id}`);
    }
    if (
      typeof scenario.screenshot !== "string" ||
      path.basename(scenario.screenshot) !== scenario.screenshot ||
      path.extname(scenario.screenshot) !== ".png"
    ) {
      throw new Error(`Invalid screenshot name for ${scenario.id}.`);
    }
    if (screenshots.has(scenario.screenshot)) {
      throw new Error(`Duplicate screenshot name: ${scenario.screenshot}`);
    }
    if (
      "platforms" in scenario &&
      (!Array.isArray(scenario.platforms) ||
        scenario.platforms.length === 0 ||
        scenario.platforms.some((name) => !scenarioPlatforms.includes(name)))
    ) {
      throw new Error(`Invalid platforms for ${scenario.id}.`);
    }
    ids.add(scenario.id);
    screenshots.add(scenario.screenshot);
  }

  for (const flow of manifest.flows) {
    const flowPath = path.resolve(mobileRoot, flow);
    if (!flowPath.startsWith(`${mobileRoot}${path.sep}`)) {
      throw new Error(`Flow escapes the mobile workspace: ${flow}`);
    }
    if (!(await exists(flowPath))) {
      throw new Error(`Visual flow does not exist: ${flow}`);
    }
  }
  return {
    ...manifest,
    scenarios: manifest.scenarios.filter((scenario) =>
      scenarioOnPlatform(scenario, platform),
    ),
    allScenarios: manifest.scenarios,
  };
}

async function requireCaptureTools() {
  if (process.platform !== "darwin") {
    throw new Error("The first visual catalog runner currently requires macOS.");
  }
  await run("xcrun", ["--find", "simctl"], { capture: true });
  const maestroCandidates = [
    path.join(os.homedir(), ".maestro/bin/maestro"),
    "/opt/homebrew/bin/maestro",
    "/usr/local/bin/maestro",
  ];
  const maestro = maestroCandidates.find((candidate) =>
    existsSync(candidate),
  );
  if (!maestro) {
    throw new Error(
      "Maestro CLI is required. Install it with:\n" +
        "  brew tap mobile-dev-inc/tap\n" +
        "  brew install mobile-dev-inc/tap/maestro",
    );
  }
  const javaPrefixes = [
    process.env.JAVA_HOME,
    "/opt/homebrew/opt/openjdk",
    "/usr/local/opt/openjdk",
  ].filter(Boolean);
  const javaPrefix = javaPrefixes.find((candidate) =>
    existsSync(path.join(candidate, "bin/java")),
  );
  const environment = {
    MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED: "true",
    MAESTRO_CLI_NO_ANALYTICS: "1",
    MAESTRO_DRIVER_STARTUP_TIMEOUT:
      process.env.MAESTRO_DRIVER_STARTUP_TIMEOUT ?? "300000",
    ...(javaPrefix
      ? {
          JAVA_HOME: javaPrefix,
          PATH: `${path.join(javaPrefix, "bin")}:${process.env.PATH ?? ""}`,
        }
      : {}),
  };
  return { maestro, environment };
}

function runtimeName(identifier) {
  const value = identifier.split("SimRuntime.").at(-1) ?? identifier;
  return value.replace("iOS-", "iOS ").replaceAll("-", ".");
}

async function availableSimulators() {
  const result = await run(
    "xcrun",
    ["simctl", "list", "devices", "available", "-j"],
    { capture: true },
  );
  const payload = JSON.parse(result.stdout);
  return Object.entries(payload.devices).flatMap(([runtime, devices]) =>
    devices.map((device) => ({
      ...device,
      runtime,
      runtimeName: runtimeName(runtime),
    })),
  );
}

function chooseSimulator(devices, requested) {
  const phones = devices.filter((device) => device.name.startsWith("iPhone"));
  if (requested) {
    const exact = phones.find(
      (device) => device.udid === requested || device.name === requested,
    );
    if (exact) return exact;
    const partial = phones.filter((device) =>
      device.name.toLowerCase().includes(requested.toLowerCase()),
    );
    if (partial.length === 1) return partial[0];
    throw new Error(`No unique available iPhone simulator matches "${requested}".`);
  }

  const preferred = phones
    .filter((device) => device.name === "iPhone 17")
    .sort((left, right) =>
      right.runtimeName.localeCompare(left.runtimeName, undefined, {
        numeric: true,
      }),
    )[0];

  return (
    preferred ??
    phones.find((device) => device.state === "Booted") ??
    phones.find((device) => device.name === "iPhone 16 Pro") ??
    phones.find((device) => device.name.endsWith("Pro")) ??
    phones[0]
  );
}

async function prepareSimulators(requested, showSimulator) {
  const devices = await availableSimulators();
  const template = chooseSimulator(devices, requested);
  if (!template) throw new Error("No available iPhone simulator was found.");
  const simulators = [];

  for (let index = 1; index <= activeShardCount(); index += 1) {
    const name =
      `Vesta Visual ${index} — ${template.name} (${template.runtimeName})`;
    const namedDevices = devices.filter((device) => device.name === name);
    const existing = namedDevices.find(
      (device) =>
        device.runtime === template.runtime &&
        device.deviceTypeIdentifier === template.deviceTypeIdentifier,
    );
    if (namedDevices.length > 0 && !existing) {
      throw new Error(
        `${name} exists with a different runtime or device type.`,
      );
    }
    if (existing) {
      simulators.push(existing);
      continue;
    }
    const result = await run(
      "xcrun",
      [
        "simctl",
        "create",
        name,
        template.deviceTypeIdentifier,
        template.runtime,
      ],
      { capture: true },
    );
    simulators.push({
      ...template,
      name,
      udid: result.stdout.trim(),
      state: "Shutdown",
    });
  }

  await Promise.all(
    simulators.map((simulator) =>
      run(
        "xcrun",
        ["simctl", "bootstatus", simulator.udid, "-b"],
        { capture: true },
      ),
    ),
  );
  if (showSimulator) {
    await run(
      "open",
      [
        "-a",
        "Simulator",
        "--args",
        "-CurrentDeviceUDID",
        simulators[0].udid,
      ],
      { allowFailure: true },
    );
  }
  return simulators;
}

async function readSimulatorUi(udid, property) {
  const result = await run("xcrun", ["simctl", "ui", udid, property], {
    capture: true,
    allowFailure: true,
  });
  return result.code === 0 ? result.stdout.trim() : "";
}

async function normalizeSimulator(udid) {
  const previous = {
    appearance: await readSimulatorUi(udid, "appearance"),
    contentSize: await readSimulatorUi(udid, "content_size"),
  };
  await run("xcrun", ["simctl", "ui", udid, "appearance", "light"]);
  await run("xcrun", ["simctl", "ui", udid, "content_size", "large"]);
  await run("xcrun", [
    "simctl",
    "status_bar",
    udid,
    "override",
    "--time",
    "9:41",
    "--dataNetwork",
    "wifi",
    "--wifiMode",
    "active",
    "--wifiBars",
    "3",
    "--cellularMode",
    "active",
    "--cellularBars",
    "4",
    "--batteryState",
    "charged",
    "--batteryLevel",
    "100",
  ]);
  return previous;
}

async function restoreSimulator(udid, previous) {
  await run("xcrun", ["simctl", "status_bar", udid, "clear"], {
    allowFailure: true,
  });
  if (["light", "dark"].includes(previous.appearance)) {
    await run(
      "xcrun",
      ["simctl", "ui", udid, "appearance", previous.appearance],
      { allowFailure: true },
    );
  }
  if (previous.contentSize && previous.contentSize !== "unknown") {
    await run(
      "xcrun",
      ["simctl", "ui", udid, "content_size", previous.contentSize],
      { allowFailure: true },
    );
  }
}

async function onlyEntryWithExtension(directory, extension) {
  const entries = await readdir(directory);
  const matches = entries.filter((entry) => entry.endsWith(extension));
  if (matches.length !== 1) {
    throw new Error(
      `Expected one ${extension} in ${directory}, found ${matches.length}.`,
    );
  }
  return path.join(directory, matches[0]);
}

async function generatedScheme(workspace) {
  const result = await run(
    "xcodebuild",
    ["-workspace", workspace, "-list", "-json"],
    { capture: true },
  );
  const project = JSON.parse(result.stdout);
  const schemes = project.workspace?.schemes ?? project.project?.schemes ?? [];
  const workspaceName = path.basename(workspace, ".xcworkspace");
  const appScheme = schemes.find((scheme) => scheme === workspaceName);
  if (!appScheme) {
    throw new Error(
      `Could not find the ${workspaceName} app scheme among ${schemes.length} schemes.`,
    );
  }
  return appScheme;
}

function processIsRunning(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code === "EPERM";
  }
}

async function moveVisualIosToCache(iosDirectory) {
  await mkdir(path.dirname(nativeIosDirectory), { recursive: true });
  await rm(nativeIosDirectory, { recursive: true, force: true });
  await rename(iosDirectory, nativeIosDirectory);
}

async function recoverGeneratedIosSwap() {
  const iosDirectory = path.join(mobileRoot, "ios");
  const savedIosDirectory = path.join(
    nativeTransactionDirectory,
    "original-ios",
  );

  if (await exists(nativeTransactionDirectory)) {
    let state;
    try {
      state = JSON.parse(await readFile(nativeTransactionStatePath, "utf8"));
    } catch {
      state = null;
    }
    if (
      state?.pid !== process.pid &&
      processIsRunning(Number(state?.pid))
    ) {
      throw new Error(
        `Another visual native build is active (PID ${state.pid}).`,
      );
    }

    const savedIosExists = await exists(savedIosDirectory);
    if (savedIosExists) {
      if (await exists(iosDirectory)) {
        await moveVisualIosToCache(iosDirectory);
      }
      await rename(savedIosDirectory, iosDirectory);
      console.log("\nRecovered the production ios/ directory from an interrupted visual build.");
    } else if (state?.hadIos === false && (await exists(iosDirectory))) {
      await moveVisualIosToCache(iosDirectory);
    }
    await rm(nativeTransactionDirectory, { recursive: true, force: true });
  }

  const expoDirectory = path.join(mobileRoot, ".expo");
  if (!(await exists(expoDirectory))) return;
  const legacyBackups = (await readdir(expoDirectory, { withFileTypes: true }))
    .filter(
      (entry) =>
        entry.isDirectory() &&
        entry.name.startsWith("visual-native.") &&
        entry.name !== path.basename(nativeTransactionDirectory),
    )
    .map((entry) => path.join(expoDirectory, entry.name));
  const recoverable = [];
  for (const backup of legacyBackups) {
    if (await exists(path.join(backup, "ios"))) recoverable.push(backup);
    else await rm(backup, { recursive: true, force: true });
  }
  if (recoverable.length > 1) {
    throw new Error(
      `Found multiple interrupted visual iOS backups: ${recoverable.join(", ")}`,
    );
  }
  if (recoverable.length === 1) {
    if (await exists(iosDirectory)) await moveVisualIosToCache(iosDirectory);
    await rename(path.join(recoverable[0], "ios"), iosDirectory);
    await rm(recoverable[0], { recursive: true, force: true });
    console.log("\nRecovered the production ios/ directory from a legacy visual build backup.");
  }
}

async function withGeneratedIos(callback) {
  await recoverGeneratedIosSwap();
  await mkdir(path.join(mobileRoot, ".expo"), { recursive: true });
  await mkdir(path.dirname(nativeIosDirectory), { recursive: true });
  await mkdir(nativeTransactionDirectory, { recursive: false });
  const iosDirectory = path.join(mobileRoot, "ios");
  const savedIosDirectory = path.join(
    nativeTransactionDirectory,
    "original-ios",
  );
  const hadIos = await exists(iosDirectory);
  const hadCachedIos = await exists(nativeIosDirectory);
  await atomicWriteFile(
    nativeTransactionStatePath,
    `${JSON.stringify({ pid: process.pid, hadIos, hadCachedIos })}\n`,
  );

  let reusable = false;
  let result;
  let interruptedSignal;
  const recordInterruption = (signal) => {
    interruptedSignal ??= signal;
    process.exitCode = signal === "SIGINT" ? 130 : 143;
  };
  const onSigint = () => recordInterruption("SIGINT");
  const onSigterm = () => recordInterruption("SIGTERM");
  process.once("SIGINT", onSigint);
  process.once("SIGTERM", onSigterm);

  try {
    if (hadIos) await rename(iosDirectory, savedIosDirectory);
    if (hadCachedIos) await rename(nativeIosDirectory, iosDirectory);
    result = await callback(iosDirectory, hadCachedIos);
    reusable = !interruptedSignal;
  } finally {
    const savedIosExists = await exists(savedIosDirectory);
    const ownsCurrentIos = savedIosExists || !hadIos;
    let visualHandled = !ownsCurrentIos || !(await exists(iosDirectory));
    let cleanupError;
    try {
      if (!visualHandled) {
        if (reusable) await moveVisualIosToCache(iosDirectory);
        else await rm(iosDirectory, { recursive: true, force: true });
        visualHandled = true;
      }
    } catch (error) {
      cleanupError = error;
    }

    let originalRestored = !savedIosExists;
    try {
      if (savedIosExists) {
        if (await exists(iosDirectory)) {
          const recoveryDirectory = path.join(
            path.dirname(nativeIosDirectory),
            `recovered-ios-${Date.now()}-${process.pid}`,
          );
          await rename(iosDirectory, recoveryDirectory);
          visualHandled = true;
        }
        await rename(savedIosDirectory, iosDirectory);
        originalRestored = true;
      }
    } catch (error) {
      cleanupError = cleanupError
        ? new AggregateError(
            [cleanupError, error],
            "Could not restore the production ios/ directory.",
          )
        : error;
    }
    if (visualHandled && originalRestored) {
      await rm(nativeTransactionDirectory, { recursive: true, force: true });
    }
    process.removeListener("SIGINT", onSigint);
    process.removeListener("SIGTERM", onSigterm);
    if (cleanupError) throw cleanupError;
  }

  if (interruptedSignal) {
    throw new Error(`Visual native build interrupted by ${interruptedSignal}.`);
  }
  return result;
}

async function findBuiltApp(productsDirectory, appId) {
  const entries = await readdir(productsDirectory, { withFileTypes: true });
  for (const entry of entries) {
    if (!entry.isDirectory() || !entry.name.endsWith(".app")) continue;
    const candidate = path.join(productsDirectory, entry.name);
    const plist = path.join(candidate, "Info.plist");
    const result = await run(
      "plutil",
      ["-extract", "CFBundleIdentifier", "raw", "-o", "-", plist],
      { capture: true, allowFailure: true },
    );
    if (result.code === 0 && result.stdout.trim() === appId) return candidate;
  }
  throw new Error(`Could not find the ${appId} simulator app.`);
}

async function findCachedBuiltApp(productsDirectory, appId) {
  if (!(await exists(productsDirectory))) return null;
  try {
    return await findBuiltApp(productsDirectory, appId);
  } catch {
    return null;
  }
}

async function rebundleApp(app, environment) {
  await rm(bundleDirectory, { recursive: true, force: true });
  await mkdir(bundleDirectory, { recursive: true });
  const bundle = path.join(bundleDirectory, "main.jsbundle");

  console.log("\nUsing fast JavaScript rebundle (no Xcode build).");
  await run(
    "npx",
    [
      "expo",
      "export:embed",
      "--entry-file",
      expoRouterEntryPath,
      "--platform",
      "ios",
      "--dev",
      "false",
      "--minify",
      "false",
      "--bundle-output",
      bundle,
      "--assets-dest",
      app,
    ],
    { env: environment },
  );
  await copyFile(bundle, path.join(app, "main.jsbundle"));
  await run("codesign", ["--force", "--sign", "-", app]);
}

async function installVisualNativeHooks(iosDirectory) {
  const appDelegates = (await filesBelow(iosDirectory)).filter(
    (file) => path.basename(file) === "AppDelegate.swift",
  );
  if (appDelegates.length !== 1) {
    throw new Error(
      `Expected one generated AppDelegate.swift, found ${appDelegates.length}.`,
    );
  }

  const appDelegate = appDelegates[0];
  const hook = (await readFile(nativeAnimationHookPath, "utf8")).trimEnd();
  const source = await readFile(appDelegate, "utf8");
  if (source.includes(hook)) return;

  const anchor =
    "    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil\n" +
    "  ) -> Bool {\n";
  if (!source.includes(anchor)) {
    throw new Error("Could not install the visual AppDelegate animation hook.");
  }
  await writeFile(appDelegate, source.replace(anchor, `${anchor}${hook}\n`));
}

async function buildAndInstall(simulators, appId) {
  const buildSimulator = simulators[0];
  await mkdir(derivedDataDirectory, { recursive: true });
  const currentNativeFingerprint = await nativeInputFingerprint();
  const cachedNativeFingerprint = (await exists(nativeFingerprintPath))
    ? (await readFile(nativeFingerprintPath, "utf8")).trim()
    : "";
  const nativeCacheIsCurrent =
    currentNativeFingerprint === cachedNativeFingerprint &&
    (await exists(nativeIosDirectory));
  if (!nativeCacheIsCurrent && (await exists(nativeIosDirectory))) {
    console.log("\nNative inputs changed; regenerating the visual iOS cache.");
    await rm(nativeIosDirectory, { recursive: true, force: true });
  }
  const visualEnvironment = {
    CI: "1",
    EXPO_OVERRIDE_METRO_CONFIG: metroConfigPath,
    VESTA_APP_VARIANT: "development",
    VESTA_APP_BUNDLE_ID: appId,
    VESTA_LOCAL_IOS_NO_PUSH: "1",
  };
  const products = path.join(
    derivedDataDirectory,
    "Build/Products/Release-iphonesimulator",
  );
  const cachedApp = nativeCacheIsCurrent
    ? await findCachedBuiltApp(products, appId)
    : null;

  let app = cachedApp;
  if (app) {
    await rebundleApp(app, visualEnvironment);
  } else {
    await withGeneratedIos(async (iosDirectory, hadCachedIos) => {
      if (!hadCachedIos) {
        await run(
          "npx",
          ["expo", "prebuild", "--clean", "--platform", "ios"],
          { env: visualEnvironment },
        );
      }
      await installVisualNativeHooks(iosDirectory);
      const workspace = await onlyEntryWithExtension(
        iosDirectory,
        ".xcworkspace",
      );
      const scheme = await generatedScheme(workspace);
      await run(
        "xcodebuild",
        [
          "-workspace",
          workspace,
          "-scheme",
          scheme,
          "-quiet",
          "-configuration",
          "Release",
          "-sdk",
          "iphonesimulator",
          "-destination",
          `id=${buildSimulator.udid}`,
          "-derivedDataPath",
          derivedDataDirectory,
          "ONLY_ACTIVE_ARCH=YES",
          "build",
        ],
        { env: visualEnvironment },
      );
    });
    app = await findBuiltApp(products, appId);
    await atomicWriteFile(
      nativeFingerprintPath,
      `${currentNativeFingerprint}\n`,
    );
  }
  await Promise.all(
    simulators.map((simulator) =>
      run(
        "xcrun",
        ["simctl", "terminate", simulator.udid, appId],
        { capture: true, allowFailure: true },
      ),
    ),
  );
  await Promise.all(
    simulators.map((simulator) =>
      run(
        "xcrun",
        ["simctl", "install", simulator.udid, app],
        { capture: true },
      ),
    ),
  );
}

async function requireInstalledApp(udid, appId) {
  const result = await run(
    "xcrun",
    ["simctl", "get_app_container", udid, appId, "app"],
    { capture: true, allowFailure: true },
  );
  if (result.code !== 0) {
    throw new Error(
      `${appId} is not installed on ${udid}. Run without --skip-build first.`,
    );
  }
}

async function runMaestro(manifest, simulators, tools) {
  await rm(maestroDirectory, { recursive: true, force: true });
  await mkdir(maestroDirectory, { recursive: true });

  const flowPaths = manifest.flows.map((flow) =>
    path.resolve(mobileRoot, flow),
  );
  const bridge = await startScreenshotBridge(simulators);
  const cycle = await bridge.beginCycle(manifest);
  try {
    await run(
      tools.maestro,
      [
        `--device=${simulators.map((simulator) => simulator.udid).join(",")}`,
        "test",
        `--shard-split=${simulators.length}`,
        ...flowPaths,
        "-e",
        `APP_ID=${manifest.appId}`,
        "-e",
        "WATCH_CAPTURE_URL=",
        "-e",
        `WATCH_CAPTURE_URL_1=${bridge.urls[0]}`,
        "-e",
        `WATCH_CAPTURE_URL_2=${bridge.urls[1]}`,
        `--test-output-dir=${maestroDirectory}`,
        "--format=HTML",
        `--output=${path.join(maestroDirectory, "report.html")}`,
        "--test-suite-name=Vesta visual catalog",
      ],
      { cwd: mobileRoot, env: tools.environment, tee: true },
    );
    // Maestro exited, so every bridge callback has been served; a scenario
    // whose callback never fired is registry drift to warn about, not a hang.
    cycle.settle();
    await cycle.completion;
  } catch (error) {
    const failure = flowFailureError(error);
    bridge.fail(failure);
    await cycle.completion.catch(() => {});
    throw failure;
  } finally {
    await bridge.close();
  }
  return cycle.seen;
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

export async function pngSize(filePath) {
  const file = await readFile(filePath);
  if (
    file.length < 24 ||
    file.toString("ascii", 1, 4) !== "PNG" ||
    file.toString("ascii", 12, 16) !== "IHDR"
  ) {
    return null;
  }
  return { width: file.readUInt32BE(16), height: file.readUInt32BE(20) };
}

export async function gitMetadata() {
  const revision = await run("git", ["rev-parse", "--short", "HEAD"], {
    cwd: repositoryRoot,
    capture: true,
    allowFailure: true,
  });
  const statusResult = await run("git", ["status", "--porcelain"], {
    cwd: repositoryRoot,
    capture: true,
    allowFailure: true,
  });
  return {
    revision: revision.stdout.trim() || "unknown",
    dirty: Boolean(statusResult.stdout.trim()),
  };
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

const galleryPlatforms = ["ios", ...Object.keys(androidVariants)];
const platformLabels = {
  ios: "iOS",
  ...Object.fromEntries(
    Object.entries(androidVariants).map(([key, variant]) => [
      key,
      variant.label,
    ]),
  ),
};

// Index of the shot files on disk: platform -> filename -> {src, mtime}, with
// src relative to the gallery root so the page can load and cache-bust it.
export async function shotEntries(baseDirectory = visualDirectory) {
  const entries = Object.fromEntries(galleryPlatforms.map((platform) => [platform, {}]));
  for (const platform of galleryPlatforms) {
    const directory = path.join(baseDirectory, "shots", platform);
    let names = [];
    try {
      names = await readdir(directory);
    } catch {
      continue;
    }
    for (const name of names) {
      if (!name.endsWith(".png")) continue;
      try {
        const mtime = Math.round(
          (await stat(path.join(directory, name))).mtimeMs,
        );
        entries[platform][name] = { src: `shots/${platform}/${name}`, mtime };
      } catch {
        continue;
      }
    }
  }
  return entries;
}

// A scan warns about registry drift instead of refusing: the shot files it
// replaced stay valid either way.
export function shotDriftWarning(producedNames, manifest) {
  const expected = manifest.scenarios.map((scenario) => scenario.screenshot);
  const missing = expected.filter((name) => !producedNames.has(name));
  const unexpected = [...producedNames]
    .filter((name) => !expected.includes(name))
    .sort();
  const parts = [];
  if (missing.length > 0) parts.push(`missing: ${missing.join(", ")}`);
  if (unexpected.length > 0) parts.push(`unexpected: ${unexpected.join(", ")}`);
  return parts.join("; ");
}

function excludedNote(scenario) {
  const labels = (scenario.platforms ?? []).map(
    (platform) => platformLabels[platform] ?? platform,
  );
  return `${labels.join(" + ")} only`;
}

// Composes the page model from the scenario registry plus whatever shot files
// exist: every scenario renders both platform slots.
export function galleryView(scenarios, shots, options = {}) {
  return {
    git: options.git ?? { revision: "unknown", dirty: false },
    reports: options.reports ?? [],
    scenarios: scenarios.map((scenario) => ({
      id: scenario.id,
      title: scenario.title,
      description: scenario.description,
      group: scenario.group,
      screenshot: scenario.screenshot,
      slots: galleryPlatforms.map((platform) => {
        const label = platformLabels[platform];
        if (!scenarioOnPlatform(scenario, platform)) {
          return { platform, label, state: "excluded", note: excludedNote(scenario) };
        }
        const entry = (shots[platform] ?? {})[scenario.screenshot];
        if (!entry) {
          return { platform, label, state: "missing", note: "Not captured yet" };
        }
        return {
          platform,
          label,
          state: "captured",
          src: entry.src,
          mtime: entry.mtime,
          size: entry.size ?? null,
        };
      }),
    })),
  };
}

function slotHtml(scenario, slot) {
  const subject = `${scenario.title} on ${slot.label}`;
  const captured = slot.state === "captured";
  const image = captured ? `${slot.src}?v=${slot.mtime}` : "";
  return `
          <div class="shot" data-screenshot="${escapeHtml(
            scenario.screenshot,
          )}" data-platform="${slot.platform}" data-state="${slot.state}" data-scenario-id="${escapeHtml(
            scenario.id ?? "",
          )}" data-group="${escapeHtml(
            scenario.group ?? "",
          )}" data-title="${escapeHtml(scenario.title)}">
            <button class="preview"${
              captured ? ` data-image="${escapeHtml(image)}"` : ""
            } aria-label="Open ${escapeHtml(subject)}">
              <span class="device-screen"${
                slot.size
                  ? ` style="--shot-ratio: ${slot.size.width} / ${slot.size.height}"`
                  : ""
              }>
                ${
                  captured
                    ? `<img src="${escapeHtml(image)}" data-stamp="${slot.mtime}" alt="${escapeHtml(
                        subject,
                      )}" loading="lazy">`
                    : `<span class="missing">${escapeHtml(slot.note)}</span>`
                }
              </span>
            </button>
            <div class="shot-meta">
              <span class="platform-tag">${escapeHtml(slot.label)}</span>
              <button class="copy-ref" type="button" aria-label="Copy reference for ${escapeHtml(
                subject,
              )}">Copy ref</button>
            </div>
          </div>`;
}

export function galleryHtml(view) {
  const scenarioGroups = new Map();
  for (const scenario of view.scenarios) {
    const group = scenario.group || "Other";
    const scenarios = scenarioGroups.get(group) ?? [];
    scenarios.push(scenario);
    scenarioGroups.set(group, scenarios);
  }
  const sections = [...scenarioGroups.entries()]
    .map(([group, scenarios], sectionIndex) => {
      const cards = scenarios
        .map(
          (scenario) => `
        <article class="card">
          <div class="shots" style="--shots: ${scenario.slots.length}">${scenario.slots
            .map((slot) => slotHtml(scenario, slot))
            .join("")}</div>
          <div class="card-copy">
            <div class="card-head">
              <h3>${escapeHtml(scenario.title)}</h3>
              <button class="copy-card" type="button" aria-label="Copy reference for ${escapeHtml(
                scenario.title,
              )}">Copy ref</button>
            </div>
            <p>${escapeHtml(scenario.description)}</p>
          </div>
        </article>`,
        )
        .join("");
      const sectionId = `scenario-section-${sectionIndex}`;
      return `
    <details class="scenario-section" open data-section-group="${escapeHtml(group)}" aria-labelledby="${sectionId}">
      <summary class="section-header">
        <h2 class="section-title" id="${sectionId}">${escapeHtml(group)}</h2>
        <span class="section-count">${scenarios.length} ${
          scenarios.length === 1 ? "screen" : "screens"
        }</span>
        <span class="section-chevron" aria-hidden="true"></span>
      </summary>
      <div class="grid">${cards}</div>
    </details>`;
    })
    .join("");
  const reportLinks = view.reports
    .map(
      (link) =>
        `<a class="report" href="${escapeHtml(link.href)}">${escapeHtml(link.label)}</a>`,
    )
    .join("\n      ");
  const scanRows = galleryPlatforms
    .map(
      (platform) => `
    <div class="scan-row" data-platform="${platform}">
      <span class="scan-platform">${escapeHtml(platformLabels[platform])}</span>
      <span class="scan-last">last scan</span>
      <span class="scan-progress"></span>
      <button class="scan-button" type="button">Scan</button>
    </div>`,
    )
    .join("");
  const gentleToggle = `
    <label class="gentle-toggle" title="One simulator shard at background priority: slower, but the machine stays responsive.">
      <input type="checkbox" id="gentle-toggle" checked>
      <span>Gentle scans</span>
    </label>`;

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vesta Mobile Apps QA</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0c0a08;
      --card: #1b1916;
      --border: rgba(255, 255, 248, 0.10);
      --muted: #d5d0c8;
      --faint: #777269;
      --text: #fcfaf6;
      --accent: #d5b993;
      --gold: #d5b993;
      --gold-soft: rgba(213, 185, 147, 0.20);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 Archivo, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      gap: 20px 32px;
      max-width: 1680px;
      margin: 0 auto;
      padding: 32px 24px 22px;
    }
    h1 {
      margin: 4px 0 5px;
      font-family: "Source Serif 4", Georgia, serif;
      font-weight: 600;
      font-size: clamp(28px, 4vw, 42px);
      line-height: 1;
      letter-spacing: -.03em;
    }
    .meta {
      display: flex;
      max-width: 540px;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 6px;
    }
    .meta span, .report {
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 5px 9px;
      background: var(--card);
      color: var(--faint);
      text-decoration: none;
      font-size: 10px;
    }
    .report:hover { color: var(--text); border-color: var(--gold); }
    .scan-bar {
      display: flex;
      max-width: 1680px;
      flex-wrap: wrap;
      gap: 10px;
      margin: 0 auto;
      padding: 0 24px 10px;
    }
    .scan-row {
      display: flex;
      align-items: center;
      gap: 10px;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 6px 8px 6px 14px;
      background: var(--card);
      color: var(--faint);
      font-size: 11px;
    }
    .scan-platform { color: var(--text); font-weight: 700; }
    .scan-progress { color: var(--accent); font-weight: 700; }
    .scan-row[data-state="failed"] .scan-last { color: #ff6467; }
    .scan-button {
      border: 1px solid var(--gold);
      border-radius: 999px;
      padding: 4px 13px;
      background: var(--gold-soft);
      color: var(--gold);
      font-size: 11px;
      cursor: pointer;
    }
    .scan-button:hover:not(:disabled) { border-color: var(--accent); }
    .scan-button:disabled { opacity: .55; cursor: default; }
    .gentle-toggle {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: var(--muted);
      cursor: pointer;
      user-select: none;
    }
    .gentle-toggle input { accent-color: var(--accent); }
    main {
      max-width: 1680px;
      margin: 0 auto;
      padding: 8px 24px 64px;
    }
    .scenario-section + .scenario-section { margin-top: 48px; }
    .section-header {
      display: flex;
      align-items: baseline;
      gap: 16px;
      margin-bottom: 16px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 10px;
      cursor: pointer;
      list-style: none;
      user-select: none;
    }
    .section-header::-webkit-details-marker { display: none; }
    .section-count { margin-left: auto; }
    .section-chevron {
      flex: 0 0 auto;
      align-self: center;
      width: 8px;
      height: 8px;
      border-right: 1.5px solid var(--muted);
      border-bottom: 1.5px solid var(--muted);
      transform: rotate(45deg);
      transition: transform .15s ease;
    }
    .scenario-section:not([open]) .section-chevron { transform: rotate(-45deg); }
    .scenario-section:not([open]) .section-header { margin-bottom: 0; }
    .section-title {
      margin: 0;
      font-family: "Source Serif 4", Georgia, serif;
      font-weight: 600;
      font-size: 20px;
      line-height: 1.2;
      letter-spacing: -.02em;
    }
    .section-count {
      flex: 0 0 auto;
      color: var(--muted);
      font-size: 11px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(min(100%, 225px), 1fr));
      align-items: start;
      gap: 16px;
    }
    body[data-platforms="2"] .grid {
      grid-template-columns: repeat(auto-fill, minmax(min(100%, 410px), 1fr));
    }
    body[data-platforms="3"] .grid {
      grid-template-columns: repeat(auto-fill, minmax(min(100%, 600px), 1fr));
    }
    .card { min-width: 0; }
    .shots {
      display: grid;
      grid-template-columns: repeat(var(--shots, 1), minmax(0, 1fr));
      align-items: start;
      gap: 10px;
    }
    .shot { position: relative; min-width: 0; }
    .platform-tag {
      color: var(--muted);
      font-size: 9px;
      font-weight: 700;
      letter-spacing: .1em;
      text-transform: uppercase;
    }
    .copy-ref, .copy-card {
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 2px 9px;
      background: transparent;
      color: var(--muted);
      font-size: 10px;
      white-space: nowrap;
      cursor: pointer;
      opacity: 0;
      transition: opacity 140ms ease;
    }
    .card:hover .copy-ref, .card:hover .copy-card,
    .copy-ref:focus-visible, .copy-card:focus-visible { opacity: 1; }
    .copy-ref:hover, .copy-card:hover {
      border-color: var(--accent);
      color: var(--text);
    }
    .shot-meta {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      margin-top: 6px;
    }
    .card-head {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 8px;
    }
    .capture-status {
      position: fixed;
      top: 16px;
      left: 50%;
      z-index: 20;
      display: flex;
      max-width: min(92vw, 560px);
      align-items: center;
      gap: 11px;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 9px 14px 9px 10px;
      background: #1b1916f2;
      box-shadow: 0 12px 40px rgba(0, 0, 0, 0.55);
      opacity: 1;
      transform: translateX(-50%);
      transition: opacity 160ms ease, transform 160ms ease;
      backdrop-filter: blur(16px);
    }
    .capture-status[hidden] {
      display: flex !important;
      opacity: 0;
      pointer-events: none;
      transform: translate(-50%, -8px);
    }
    .capture-status[data-state="error"] {
      border-color: #ff6467;
      background: #241413f2;
    }
    .status-spinner {
      width: 25px;
      height: 25px;
      flex: 0 0 auto;
      border: 3px solid var(--gold-soft);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: status-spin .8s linear infinite;
    }
    .capture-status[data-state="error"] .status-spinner {
      display: grid;
      border: 0;
      background: #ff6467;
      color: #26211a;
      font-weight: 900;
      place-items: center;
      animation: none;
    }
    .capture-status[data-state="error"] .status-spinner::before { content: "!"; }
    .status-copy { min-width: 0; }
    .status-title { display: block; font-size: 12px; line-height: 1.25; }
    .status-detail {
      display: block;
      overflow: hidden;
      color: var(--muted);
      font-size: 10px;
      line-height: 1.35;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    @keyframes status-spin { to { transform: rotate(360deg); } }
    .preview {
      position: relative;
      display: block;
      width: 100%;
      border: 1px solid #4b4b55;
      border-radius: 32px;
      padding: 5px;
      background: linear-gradient(145deg, #35353c, #08080b 42%, #222228);
      box-shadow:
        0 18px 42px #0008,
        inset 0 0 0 1px #ffffff14;
      cursor: zoom-in;
    }
    .preview::before,
    .preview::after {
      content: "";
      position: absolute;
      left: -3px;
      width: 3px;
      border-radius: 2px 0 0 2px;
      background: #34343b;
    }
    .preview::before { top: 18%; height: 9%; }
    .preview::after { top: 30%; height: 14%; }
    .shot.refreshing .device-screen img,
    .shot.refreshing .device-screen .missing {
      opacity: 0.35;
    }
    .shot.refreshing .device-screen::after {
      content: "Refreshing…";
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      font-size: 12px;
      color: #b9b3a9;
      animation: refreshing-pulse 1.2s ease-in-out infinite;
    }
    @keyframes refreshing-pulse {
      50% { opacity: 0.35; }
    }
    .device-screen {
      position: relative;
      display: grid;
      width: 100%;
      aspect-ratio: var(--shot-ratio, 603 / 1311);
      place-items: center;
      overflow: hidden;
      border-radius: 27px;
      background: #08080a;
    }
    .device-screen img {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: contain;
      transition: opacity 160ms ease;
    }
    .preview:hover img { opacity: .88; }
    .missing { color: #9a948b; }
    .card-copy {
      margin-top: 9px;
      border: 1px solid var(--border);
      border-radius: 13px;
      padding: 11px 12px 12px;
      background: var(--card);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35), inset 0 0 0 1px rgba(252, 250, 246, 0.10);
    }
    h3 { margin: 0 0 4px; font-size: 16px; line-height: 1.2; letter-spacing: -.015em; }
    .card p {
      display: -webkit-box;
      overflow: hidden;
      margin: 0 0 8px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.4;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
    }
    dialog {
      width: min(96vw, 1100px);
      height: min(94vh, 1100px);
      border: 1px solid var(--border);
      border-radius: 24px;
      padding: 0;
      background: #08080a;
      box-shadow: 0 30px 100px #000b;
    }
    dialog::backdrop { background: #000b; backdrop-filter: blur(8px); }
    dialog img { width: 100%; height: 100%; object-fit: contain; }
    dialog button {
      position: absolute;
      top: 14px;
      right: 14px;
      width: 38px;
      height: 38px;
      border: 1px solid #ffffff33;
      border-radius: 50%;
      background: #111d;
      color: white;
      font-size: 20px;
      cursor: pointer;
    }
    [hidden] { display: none !important; }
    @media (max-width: 720px) {
      header { grid-template-columns: 1fr; padding: 24px 16px 18px; }
      .meta { justify-content: flex-start; }
      main {
        padding: 4px 16px 48px;
      }
      .scenario-section + .scenario-section { margin-top: 36px; }
      .grid {
        grid-template-columns: repeat(auto-fill, minmax(min(100%, 160px), 1fr));
        gap: 10px;
      }
    }
  </style>
</head>
<body data-platforms="${galleryPlatforms.length}" data-revision="${escapeHtml(view.git.revision)}">
  <div class="capture-status" id="capture-status" data-state="ready" role="status" aria-live="polite" hidden>
    <span class="status-spinner" aria-hidden="true"></span>
    <span class="status-copy">
      <strong class="status-title">Recapturing screenshots</strong>
      <span class="status-detail">Running the simulator shards…</span>
    </span>
  </div>
  <header>
    <div>
      <h1>Vesta Mobile Apps QA</h1>
    </div>
    <div class="meta">
      <span>${escapeHtml(view.git.revision)}${view.git.dirty ? " · dirty" : ""}</span>
      ${reportLinks}
    </div>
  </header>
  <section class="scan-bar" aria-label="Capture runs">${scanRows}${gentleToggle}
  </section>
  <main>${sections}</main>
  <dialog id="lightbox">
    <button aria-label="Close">×</button>
    <img alt="">
  </dialog>
  <script>
    const dialog = document.querySelector("#lightbox");
    const dialogImage = dialog.querySelector("img");
    document.querySelectorAll(".preview").forEach((button) => {
      button.addEventListener("click", () => {
        const image = button.querySelector("img");
        if (!image || !button.dataset.image) return;
        dialogImage.src = button.dataset.image;
        dialogImage.alt = image.alt;
        dialog.showModal();
      });
    });
    async function writeClipboard(text) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch {
        // Fall through to the textarea path below.
      }
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      let copied = false;
      try {
        copied = document.execCommand("copy");
      } catch {
        copied = false;
      }
      area.remove();
      return copied;
    }
    function refHeader(shot) {
      return [
        "group: " + shot.dataset.group + " | title: " + shot.dataset.title,
        "rev: " + document.body.dataset.revision,
      ];
    }
    function shotImage(shot) {
      return shot.querySelector(".preview").dataset.image || "not captured";
    }
    async function copyWithFeedback(copyButton, lines) {
      const label = copyButton.textContent;
      const copied = await writeClipboard(lines.join("\\n"));
      copyButton.textContent = copied ? "Copied" : "Copy failed";
      window.setTimeout(() => {
        copyButton.textContent = label;
      }, 1200);
    }
    document.querySelectorAll(".copy-ref").forEach((copyButton) => {
      copyButton.addEventListener("click", () => {
        const shot = copyButton.closest(".shot");
        void copyWithFeedback(copyButton, [
          "visual-ref: " + shot.dataset.scenarioId +
            " [" + shot.dataset.platform + "]",
          ...refHeader(shot),
          "image: " + shotImage(shot),
        ]);
      });
    });
    document.querySelectorAll(".copy-card").forEach((copyButton) => {
      copyButton.addEventListener("click", () => {
        const shots = [...copyButton.closest(".card").querySelectorAll(".shot")];
        void copyWithFeedback(copyButton, [
          "visual-ref: " + shots[0].dataset.scenarioId,
          ...refHeader(shots[0]),
          ...shots.map(
            (shot) => shot.dataset.platform + ": " + shotImage(shot),
          ),
        ]);
      });
    });
    dialog.querySelector("button").addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    const status = document.querySelector("#capture-status");
    const statusTitle = status.querySelector(".status-title");
    const statusDetail = status.querySelector(".status-detail");
    function showCaptureStatus(nextStatus) {
      const state = nextStatus?.state ?? "ready";
      document.body.dataset.captureState = state;
      status.dataset.state = state;
      status.hidden = state === "ready";
      if (state === "capturing") {
        const elapsed = nextStatus.startedAt
          ? Math.max(0, Math.round((Date.now() - Date.parse(nextStatus.startedAt)) / 1000))
          : 0;
        statusTitle.textContent = nextStatus.message || "Recapturing screenshots";
        const context = nextStatus.detail || "Running the simulator shards";
        statusDetail.textContent = context + " · " + elapsed + "s";
      } else if (state === "error") {
        statusTitle.textContent = nextStatus.message || "Screenshot refresh failed";
        statusDetail.textContent = nextStatus.detail || "Fix the issue and save again.";
      }
    }
    const collapsedGroups = new Set(
      JSON.parse(localStorage.getItem("visual-collapsed") || "[]"),
    );
    document.querySelectorAll(".scenario-section").forEach((section) => {
      const group = section.dataset.sectionGroup;
      section.open = !collapsedGroups.has(group);
      section.addEventListener("toggle", () => {
        if (section.open) collapsedGroups.delete(group);
        else collapsedGroups.add(group);
        localStorage.setItem("visual-collapsed", JSON.stringify([...collapsedGroups]));
      });
    });
    const gentleToggle = document.querySelector("#gentle-toggle");
    gentleToggle.checked = localStorage.getItem("visual-gentle") !== "0";
    gentleToggle.addEventListener("change", () => {
      localStorage.setItem("visual-gentle", gentleToggle.checked ? "1" : "0");
    });
    document.querySelectorAll(".scan-row .scan-button").forEach((button) => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        const platform = button.closest(".scan-row").dataset.platform;
        const gentle = gentleToggle.checked ? "1" : "0";
        try {
          await fetch("capture/" + platform + "?gentle=" + gentle, {
            method: "POST",
          });
        } catch {
          button.disabled = false;
        }
      });
    });
    function applyShots(payload) {
      document.querySelectorAll(".shot[data-screenshot]").forEach((shot) => {
        if (shot.dataset.state === "excluded") return;
        const entry = (payload[shot.dataset.platform] ?? {})[
          shot.dataset.screenshot
        ];
        if (!entry) return;
        const button = shot.querySelector(".preview");
        const screen = shot.querySelector(".device-screen");
        let image = screen.querySelector("img");
        if (!image) {
          screen.textContent = "";
          image = document.createElement("img");
          image.alt = shot.dataset.screenshot;
          screen.appendChild(image);
          shot.dataset.state = "captured";
        }
        const stamp = String(entry.mtime);
        if (image.dataset.stamp !== stamp) {
          const src = entry.src + "?v=" + stamp;
          image.src = src;
          image.dataset.stamp = stamp;
          button.dataset.image = src;
        }
      });
    }
    function updateScanRows(payload, status) {
      document.querySelectorAll(".scan-row").forEach((row) => {
        const platform = row.dataset.platform;
        const run = (payload.runs ?? {})[platform];
        const statusRun = Boolean(
          status &&
            status.state === "capturing" &&
            status.platform === platform &&
            status.startedAt,
        );
        const running = Boolean(run && run.running) || statusRun;
        const button = row.querySelector(".scan-button");
        button.disabled = running;
        button.textContent = running ? "Scanning" : "Scan";
        const entries = payload[platform] ?? {};
        const slots = document.querySelectorAll(
          '.shot[data-platform="' + platform + '"]:not([data-state="excluded"])',
        );
        // While a scan runs, count this run's replacements from zero; idle, count files on disk.
        const startedMs = running
          ? Date.parse(
              (run && run.startedAt) || (status && status.startedAt) || "",
            )
          : 0;
        let have = 0;
        slots.forEach((slot) => {
          const entry = entries[slot.dataset.screenshot];
          if (!entry) return;
          if (!running || entry.mtime >= startedMs) have += 1;
        });
        row.querySelector(".scan-progress").textContent =
          have + "/" + slots.length;
        const failed = Boolean(run && !running && run.exitCode);
        row.dataset.state = failed ? "failed" : "ok";
        const mtimes = Object.values(entries).map((entry) => entry.mtime);
        row.querySelector(".scan-last").textContent = failed
          ? "last scan failed, see capture-" + platform + ".log"
          : "last scan " +
            (mtimes.length
              ? new Date(Math.max.apply(null, mtimes)).toLocaleString()
              : "never");
      });
    }
    function markRefreshing(status, payload) {
      const capturing = Boolean(
        status &&
          status.state === "capturing" &&
          status.platform &&
          status.startedAt,
      );
      const startedMs = capturing ? Date.parse(status.startedAt) : 0;
      document.querySelectorAll(".shot").forEach((shot) => {
        const applies =
          capturing &&
          shot.dataset.platform === status.platform &&
          shot.dataset.state !== "excluded";
        if (!applies) {
          shot.classList.remove("refreshing");
          return;
        }
        const entry = (payload[status.platform] ?? {})[
          shot.dataset.screenshot
        ];
        const replaced = Boolean(entry && entry.mtime >= startedMs);
        shot.classList.toggle("refreshing", !replaced);
      });
    }
    let lastStatus = null;
    window.setInterval(async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const [statusResponse, shotsResponse] = await Promise.all([
          fetch("status.json", { cache: "no-store" }),
          fetch("shots.json", { cache: "no-store" }),
        ]);
        if (statusResponse.ok) {
          lastStatus = await statusResponse.json();
          showCaptureStatus(lastStatus);
        }
        if (shotsResponse.ok) {
          const payload = await shotsResponse.json();
          applyShots(payload);
          updateScanRows(payload, lastStatus);
          markRefreshing(lastStatus, payload);
        }
      } catch {
        // The local server may be between restarts.
      }
    }, 500);
  </script>
</body>
</html>`;
}

export async function composeGallery() {
  const manifest = await loadManifest();
  const shots = await shotEntries();
  for (const platform of galleryPlatforms) {
    for (const entry of Object.values(shots[platform])) {
      try {
        entry.size = await pngSize(path.join(visualDirectory, entry.src));
      } catch {
        entry.size = null;
      }
    }
  }
  const reports = [];
  if (await exists(path.join(maestroDirectory, "report.html"))) {
    reports.push({ label: "iOS Maestro report", href: "maestro/report.html" });
  }
  for (const [variant, config] of Object.entries(androidVariants)) {
    const workDirectory = androidWorkDirectory(variant);
    if (!(await exists(path.join(workDirectory, "maestro/report.html")))) {
      continue;
    }
    reports.push({
      label: `${config.label} Maestro report`,
      href: `${path.basename(workDirectory)}/maestro/report.html`,
    });
  }
  return galleryView(manifest.allScenarios, shots, {
    git: await gitMetadata(),
    reports,
  });
}

function safeStaticPath(url, baseDirectory) {
  const pathname = decodeURIComponent(new URL(url, "http://localhost").pathname);
  const relative = pathname === "/" ? "index.html" : pathname.slice(1);
  const target = path.resolve(baseDirectory, relative);
  const relation = path.relative(baseDirectory, target);
  if (relation.startsWith("..") || path.isAbsolute(relation)) return null;
  return target;
}

export async function serveCatalog(port, shouldOpen) {
  const baseDirectory = visualDirectory;
  const idleRun = { running: false, startedAt: null, finishedAt: null, exitCode: null };
  const captureRuns = Object.fromEntries(
    galleryPlatforms.map((platform) => [platform, { ...idleRun }]),
  );
  const androidScript = path.join(
    mobileRoot,
    "scripts/visual-catalog-android.mjs",
  );
  const captureScripts = {
    ios: fileURLToPath(import.meta.url),
    ...Object.fromEntries(
      Object.keys(androidVariants).map((variant) => [variant, androidScript]),
    ),
  };
  const startCaptureRun = (platform, gentle) => {
    if (captureRuns[platform].running) return false;
    const logFile = openSync(
      path.join(visualDirectory, `capture-${platform}.log`),
      "w",
    );
    const child = spawn(
      process.execPath,
      [
        captureScripts[platform],
        "capture",
        "--no-serve",
        "--no-open",
        ...(platform.startsWith("android") ? ["--variant", platform] : []),
        ...(gentle ? ["--gentle"] : []),
      ],
      { cwd: mobileRoot, env: process.env, stdio: ["ignore", logFile, logFile] },
    );
    closeSync(logFile);
    captureRuns[platform] = {
      running: true,
      startedAt: new Date().toISOString(),
      finishedAt: null,
      exitCode: null,
    };
    const finish = (exitCode) => {
      captureRuns[platform] = {
        ...captureRuns[platform],
        running: false,
        finishedAt: new Date().toISOString(),
        exitCode,
      };
    };
    child.on("error", () => finish(1));
    child.on("exit", (code) => finish(code ?? 1));
    return true;
  };
  const server = createServer(async (request, response) => {
    const pathname = decodeURIComponent(
      new URL(request.url ?? "/", "http://localhost").pathname,
    );
    if (pathname === "/status.json") {
      response.writeHead(200, {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
      });
      response.end(`${JSON.stringify(await currentRunStatus())}\n`);
      return;
    }
    if (pathname === "/shots.json") {
      response.writeHead(200, {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
      });
      response.end(
        `${JSON.stringify({ ...(await shotEntries()), runs: captureRuns })}\n`,
      );
      return;
    }
    if (
      pathname.startsWith("/capture/") &&
      galleryPlatforms.includes(pathname.split("/")[2])
    ) {
      const platform = pathname.split("/")[2];
      if (request.method !== "POST") {
        response.writeHead(405).end("POST required");
        return;
      }
      const gentle =
        new URL(request.url ?? "/", "http://localhost").searchParams.get(
          "gentle",
        ) !== "0";
      const started = startCaptureRun(platform, gentle);
      response.writeHead(started ? 202 : 409, {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
      });
      response.end(`${JSON.stringify({ started, run: captureRuns[platform] })}\n`);
      return;
    }
    if (pathname === "/" || pathname === "/index.html") {
      try {
        const html = galleryHtml(await composeGallery());
        response.writeHead(200, {
          "Content-Type": "text/html; charset=utf-8",
          "Cache-Control": "no-store",
        });
        response.end(html);
      } catch (error) {
        response
          .writeHead(500)
          .end(`Could not compose the gallery: ${error.message}`);
      }
      return;
    }
    const target = safeStaticPath(request.url ?? "/", baseDirectory);
    if (!target) {
      response.writeHead(403).end("Forbidden");
      return;
    }
    try {
      const info = await stat(target);
      if (!info.isFile()) throw new Error("Not a file");
      const content = await readFile(target);
      response.writeHead(200, {
        "Content-Type":
          mimeTypes.get(path.extname(target)) ?? "application/octet-stream",
        "Cache-Control": "no-store",
      });
      response.end(content);
    } catch {
      response.writeHead(404).end("Not found");
    }
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", resolve);
  });
  const url = `http://127.0.0.1:${port}`;
  console.log(`\nVisual catalog: ${url}`);
  if (shouldOpen) {
    await run("open", [url], { allowFailure: true });
  }
  await new Promise((resolve) => {
    const stop = () => server.close(resolve);
    process.once("SIGINT", stop);
    process.once("SIGTERM", stop);
  });
}

async function prepareCaptureSession(options) {
  await recoverGeneratedIosSwap();
  await assertHarnessBoundary();
  const manifest = await loadManifest();
  const tools = await requireCaptureTools();
  await mkdir(visualDirectory, { recursive: true });
  const simulators = await prepareSimulators(
    options.device,
    options.showSimulator,
  );
  console.log(
    `\nUsing ${simulators.length} simulator shards:\n${simulators
      .map(
        (simulator, index) =>
          `  ${index + 1}. ${simulator.name} (${simulator.runtimeName})`,
      )
      .join("\n")}`,
  );
  const previousUi = await Promise.all(
    simulators.map((simulator) => normalizeSimulator(simulator.udid)),
  );
  return {
    appId: manifest.appId,
    previousUi,
    simulators,
    tools,
  };
}

async function runCaptureIteration(options, session, onPhase = async () => {}) {
  await assertHarnessBoundary();
  const manifest = await loadManifest();
  if (manifest.appId !== session.appId) {
    throw new Error(
      "The visual appId changed. Restart the capture command before continuing.",
    );
  }
  await onPhase(
    options.skipBuild
      ? "Checking the installed visual app"
      : "Bundling and installing the visual app",
  );
  await installVisualApp(options, session, manifest);
  await onPhase(
    `Running ${manifest.flows.length} flows on ${session.simulators.length} simulator shard(s)`,
  );
  const produced = await runMaestro(manifest, session.simulators, session.tools);
  return { produced, warning: reportShotDrift(produced, manifest) };
}

async function installVisualApp(options, session, manifest) {
  const { simulators } = session;
  if (options.skipBuild) {
    await Promise.all(
      simulators.map((simulator) =>
        requireInstalledApp(simulator.udid, manifest.appId),
      ),
    );
    return;
  }
  if (!options.cleanNative && (await jsBundleCurrent("ios"))) {
    try {
      await Promise.all(
        simulators.map((simulator) =>
          requireInstalledApp(simulator.udid, manifest.appId),
        ),
      );
      console.log("\nJS inputs unchanged; reusing the installed bundle.");
      return;
    } catch {
      // Not installed after all; fall through to the build.
    }
  }
  if (options.cleanNative) {
    await rm(nativeIosDirectory, { recursive: true, force: true });
    await rm(nativeFingerprintPath, { force: true });
  }
  await buildAndInstall(simulators, manifest.appId);
  await recordJsBundle("ios");
}

async function closeCaptureSession(session) {
  await Promise.all(
    session.simulators.map((simulator, index) =>
      restoreSimulator(simulator.udid, session.previousUi[index]),
    ),
  );
}

async function capture(options) {
  const startedAt = new Date().toISOString();
  const phase = (message) =>
    publishRunStatus("capturing", { message, startedAt, platform: "ios" });
  try {
    await phase("Preparing simulators");
    const session = await prepareCaptureSession(options);
    let result;
    try {
      result = await runCaptureIteration(options, session, phase);
    } finally {
      await closeCaptureSession(session);
    }
    await publishRunStatus("ready", {
      message: `Captured ${result.produced.size} screenshots`,
      detail: result.warning,
    });
  } catch (error) {
    await publishRunStatus("error", {
      message: "Capture failed",
      detail: error instanceof Error ? error.message : String(error),
    });
    throw error;
  }

  if (options.serve) await serveCatalog(options.port, options.open);
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

const simulatorApplication =
  "/Applications/Xcode.app/Contents/Developer/Applications/Simulator.app/Contents/MacOS/Simulator";

async function findSimulatorApplication(udid) {
  const result = await run(
    "pgrep",
    ["-f", `${simulatorApplication} -CurrentDeviceUDID ${udid}`],
    { capture: true, allowFailure: true, quiet: true },
  );
  const pid = Number(result.stdout.trim().split("\n")[0]);
  return Number.isInteger(pid) && pid > 0 ? pid : null;
}

async function ensureHiddenSimulatorApplication(udid) {
  let pid = await findSimulatorApplication(udid);
  let created = false;
  if (pid === null) {
    await run(
      "open",
      [
        "-gj",
        "-n",
        "-a",
        "Simulator",
        "--args",
        "-CurrentDeviceUDID",
        udid,
        "-ConnectHardwareKeyboard",
        "0",
      ],
      { capture: true, quiet: true },
    );
    created = true;
    for (let attempt = 0; attempt < 30 && pid === null; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 200));
      pid = await findSimulatorApplication(udid);
    }
  }
  if (pid === null) {
    throw new Error("Could not start the hidden Simulator keyboard host.");
  }
  return { created, pid };
}

async function showSimulatorSoftwareKeyboard(udid) {
  const host = await ensureHiddenSimulatorApplication(udid);
  const script = [
    'tell application "System Events"',
    `set simulatorProcess to first process whose unix id is ${host.pid}`,
    "tell simulatorProcess",
    'click menu item "Toggle Software Keyboard" of menu 1 of menu item "Keyboard" of menu 1 of menu bar item "I/O" of menu bar 1',
    "end tell",
    "end tell",
  ].join("\n");
  let failure = "";
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const result = await run("osascript", ["-e", script], {
      capture: true,
      allowFailure: true,
      quiet: true,
    });
    if (result.code === 0) return host;
    failure = result.stderr.trim();
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(
    `Could not show the iOS software keyboard.${failure ? ` ${failure}` : ""}`,
  );
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

async function startScreenshotBridge(simulators) {
  let cycle;
  const createdKeyboardHostPids = new Set();
  const routes = new Map(
    simulators.map((simulator, index) => [
      `/__visual_capture/${index + 1}`,
      simulator,
    ]),
  );
  const server = createServer(async (request, response) => {
    const pathname = new URL(
      request.url ?? "/",
      "http://127.0.0.1",
    ).pathname;
    const simulator = routes.get(pathname);
    if (request.method !== "POST" || !simulator) {
      response.writeHead(404).end("Not found");
      return;
    }
    try {
      const payload = await readRequestJson(request);
      if (payload.action === "show-software-keyboard") {
        const host = await showSimulatorSoftwareKeyboard(simulator.udid);
        if (host.created) createdKeyboardHostPids.add(host.pid);
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
      // Capture to a temporary path, then rename: the shot registry entry is
      // replaced atomically, so a gallery poll never reads a torn PNG.
      const target = path.join(iosShotsDirectory, screenshot);
      const temporary = `${target}.${process.pid}.tmp`;
      await run(
        "xcrun",
        ["simctl", "io", simulator.udid, "screenshot", "--type=png", temporary],
        { capture: true, quiet: true },
      );
      await rename(temporary, target);
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
    urls: simulators.map(
      (_simulator, index) => `${baseUrl}/__visual_capture/${index + 1}`,
    ),
    async beginCycle(manifest, timeoutMs = 120_000) {
      if (cycle && !cycle.completed) {
        throw new Error("A screenshot cycle is already active.");
      }
      await mkdir(iosShotsDirectory, { recursive: true });
      const expected = new Set(
        manifest.scenarios.map((scenario) => scenario.screenshot),
      );
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
    cancel(detail) {
      if (!cycle || cycle.completed) return;
      cycle.completed = true;
      cycle.watchdog.cancel();
      cycle.reject(new CaptureSupersededError(detail));
    },
    async close() {
      if (cycle && !cycle.completed) {
        cycle.completed = true;
        cycle.watchdog.cancel();
        cycle.reject(new Error("Screenshot bridge stopped."));
      }
      await new Promise((resolve) => server.close(resolve));
      for (const pid of createdKeyboardHostPids) {
        try {
          process.kill(pid, "SIGTERM");
        } catch {}
      }
    },
  };
}

async function syncWatchFlows(manifest) {
  await mkdir(watchFlowsDirectory, { recursive: true });
  const flowPaths = [];
  const changedShards = [];
  const flowShards = assignFlowsToShards(manifest.flows, shardCount);
  for (const [index, flows] of flowShards.entries()) {
    const sources = await Promise.all(
      flows.map(async (flow) => ({
        label: flow,
        source: await readFile(path.resolve(mobileRoot, flow), "utf8"),
      })),
    );
    const target = path.join(watchFlowsDirectory, `shard-${index + 1}.yml`);
    const changed = await writeFileIfChanged(
      target,
      continuousShardFlow(manifest.appId, index + 1, sources),
    );
    if (changed) changedShards.push(index);
    flowPaths.push(target);
  }
  const callbackSource = await readFile(
    path.join(mobileRoot, "maestro/visual/capture-screenshot.js"),
    "utf8",
  );
  await writeFileIfChanged(
    path.join(watchFlowsDirectory, "capture-screenshot.js"),
    callbackSource,
  );
  return { changedShards, flowPaths };
}

const ansiEscapePattern = /\u001B\[[0-?]*[ -/]*[@-~]/g;

export function createMaestroFailureParser(onFailure) {
  let tail = "";
  let reported = false;

  return {
    beginRun() {
      tail = "";
      reported = false;
    },
    consume(chunk) {
      if (reported) return;
      const output = `${tail}${String(chunk)}`.replace(ansiEscapePattern, "");
      const lines = output.split(/[\r\n]+/);
      tail = (lines.pop() ?? "").slice(-2_000);
      for (const candidate of [...lines, tail]) {
        const line = candidate.trim();
        if (!/\bFAILED\b/.test(line) && !line.includes("❌")) continue;
        reported = true;
        const failedStep = line.includes("❌")
          ? line.slice(line.indexOf("❌") + "❌".length).trim()
          : line;
        onFailure(failedStep);
        return;
      }
    },
  };
}

function startContinuousMaestro(session, manifest, flowPaths, bridge) {
  let stopping = false;
  let failure;
  let stopPromise;
  if (flowPaths.length !== session.simulators.length) {
    throw new Error(
      `Expected ${session.simulators.length} continuous Maestro shard flows, received ${flowPaths.length}.`,
    );
  }
  const children = flowPaths.map((flow, index) => {
    const child = spawn(
      session.tools.maestro,
      [
        `--device=${session.simulators[index].udid}`,
        "test",
        "--continuous",
        "--no-ansi",
        flow,
        "-e",
        `APP_ID=${manifest.appId}`,
        "-e",
        `WATCH_CAPTURE_URL=${bridge.urls[index]}`,
      ],
      {
        cwd: watchFlowsDirectory,
        env: { ...process.env, ...session.tools.environment },
        stdio: ["pipe", "pipe", "pipe"],
      },
    );
    let stdout = "";
    let stderr = "";
    const reportFlowFailure = (failedStep) =>
      bridge.fail(
        new Error(`Maestro watch shard ${index + 1} failed: ${failedStep}`),
      );
    const stdoutParser = createMaestroFailureParser(reportFlowFailure);
    const stderrParser = createMaestroFailureParser(reportFlowFailure);
    child.stdout.on("data", (chunk) => {
      stdout = `${stdout}${chunk}`.slice(-12_000);
      stdoutParser.consume(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr = `${stderr}${chunk}`.slice(-12_000);
      stderrParser.consume(chunk);
    });
    child.stdin.on("error", (error) => {
      if (stopping) return;
      failure = error;
      bridge.fail(error);
    });
    child.on("error", (error) => {
      failure = error;
      bridge.fail(error);
    });
    child.on("exit", (code, signal) => {
      if (stopping) return;
      const output = [stdout.trim(), stderr.trim()].filter(Boolean).join("\n");
      failure = new Error(
        `Maestro watch shard ${index + 1} stopped with ${
          code ?? signal
        }.${output ? `\n${output}` : ""}`,
      );
      bridge.fail(failure);
    });
    return { child, stdoutParser, stderrParser };
  });

  return {
    isHealthy() {
      return (
        !failure &&
        children.every(
          ({ child }) => child.exitCode === null && child.signalCode === null,
        )
      );
    },
    trigger(indices = children.map((_entry, index) => index)) {
      if (failure) throw failure;
      for (const index of indices) {
        const entry = children[index];
        if (!entry) throw new Error(`Unknown Maestro shard index: ${index}`);
        entry.stdoutParser.beginRun();
        entry.stderrParser.beginRun();
        entry.child.stdin.write("\n");
      }
    },
    async stop() {
      if (stopPromise) return stopPromise;
      stopping = true;
      stopPromise = Promise.all(
        children.map(
          ({ child }) =>
            new Promise((resolve) => {
              if (child.exitCode !== null || child.signalCode !== null) {
                resolve();
                return;
              }
              const timer = setTimeout(() => {
                child.kill("SIGKILL");
                resolve();
              }, 3000);
              child.once("exit", () => {
                clearTimeout(timer);
                resolve();
              });
              child.kill("SIGINT");
            }),
        ),
      );
      await stopPromise;
    },
  };
}

export function assignFlowsToShards(flowPaths, count) {
  if (!Number.isInteger(count) || count < 1) {
    throw new Error("At least one Maestro shard is required.");
  }
  const shards = Array.from({ length: count }, () => []);
  flowPaths.forEach((flow, index) => shards[index % count].push(flow));
  return shards;
}

export function continuousShardFlow(appId, index, flowSources) {
  const commands = flowSources.map(({ label, source }) => {
    const divider = /^---\s*$/m.exec(source);
    if (!divider) throw new Error(`Maestro flow is missing ---: ${label}`);
    return source.slice(divider.index + divider[0].length).trim();
  });
  return `appId: ${appId}
name: Vesta visual catalog shard ${index}
tags:
  - visual
  - watch
---
${commands.join("\n\n")}\n`;
}

function reportShotDrift(seen, manifest) {
  const warning = shotDriftWarning(seen, manifest);
  if (warning) console.warn(`\nShot registry drift: ${warning}`);
  console.log(`\nCaptured ${seen.size} mobile screenshots into .visual/shots/ios.`);
  return warning;
}

export function shouldIgnoreWatchPath(changedPath) {
  const basename = changedPath ? path.basename(changedPath) : "";
  return (
    !changedPath ||
    changedPath.includes(`${path.sep}.`) ||
    changedPath.endsWith("~") ||
    changedPath.endsWith(".swp") ||
    basename.endsWith(".tmp") ||
    basename.includes(".tmp.") ||
    basename.endsWith(".snap") ||
    /\.(?:test|spec)\.[cm]?[jt]sx?$/.test(basename) ||
    changedPath.split(path.sep).includes("__tests__")
  );
}

export function watchChangePath(target, changedPath) {
  return shouldIgnoreWatchPath(changedPath) ? target : changedPath;
}

function visualWatchTargets() {
  const targets = [
    {
      target: path.join(mobileRoot, "app"),
      rebuild: true,
      recursive: true,
      restart: false,
      native: false,
    },
    {
      target: path.join(mobileRoot, "src"),
      rebuild: true,
      recursive: true,
      restart: false,
      native: false,
    },
    {
      target: path.join(mobileRoot, "assets"),
      rebuild: true,
      recursive: true,
      restart: false,
      native: false,
    },
    {
      target: path.join(mobileRoot, "visual/harness"),
      rebuild: true,
      recursive: true,
      restart: false,
      native: false,
    },
    {
      target: metroConfigPath,
      rebuild: true,
      recursive: false,
      restart: false,
      native: false,
    },
    {
      target: path.join(mobileRoot, "maestro/visual"),
      rebuild: false,
      recursive: true,
      restart: false,
      native: false,
    },
    {
      target: manifestPath,
      rebuild: false,
      recursive: false,
      restart: true,
      native: false,
    },
    {
      target: path.resolve(mobileRoot, "../core/src"),
      rebuild: true,
      recursive: true,
      restart: false,
      native: false,
    },
    ...nativeInputTargets().map((target) => ({
      target,
      rebuild: true,
      recursive: statSyncDirectory(target),
      restart: false,
      native: true,
    })),
  ];
  return targets.filter(({ target }) => existsSync(target));
}

function statSyncDirectory(target) {
  return existsSync(target) && statSync(target).isDirectory();
}

async function watchTargetFingerprints(targets) {
  const fingerprints = new Map();
  await Promise.all(
    targets.map(async ({ target }) => {
      fingerprints.set(
        target,
        await fingerprintPaths(
          [target],
          (file) => !shouldIgnoreWatchPath(file),
        ),
      );
    }),
  );
  return fingerprints;
}

async function watchCatalog(options) {
  const targets = visualWatchTargets();
  const startupFingerprints = await watchTargetFingerprints(targets);
  const session = await prepareCaptureSession(options);
  let bridge;
  let processes;
  let debounceTimer;
  let watchers = [];
  try {
    await assertHarnessBoundary();
    let manifest = await loadManifest();
    await installVisualApp(options, session, manifest);
    bridge = await startScreenshotBridge(session.simulators);

    const initialCycle = await bridge.beginCycle(manifest);
    const { flowPaths: initialFlows } = await syncWatchFlows(manifest);
    processes = startContinuousMaestro(
      session,
      manifest,
      initialFlows,
      bridge,
    );
    console.log("\nStarting persistent Maestro sessions…");
    try {
      await initialCycle.completion;
      const warning = reportShotDrift(initialCycle.seen, manifest);
      setVisualCatalogStatus("ready", {
        message: "Screenshots are up to date",
        detail: warning,
      });
    } catch (error) {
      setVisualCatalogStatus("error", {
        message: "Screenshot refresh failed",
        detail: error.message,
      });
      console.error(`\nInitial watch capture failed: ${error.message}`);
      console.error(
        "The watcher is still running. Fix the error and save again to retry.",
      );
    }

    let running = false;
    let queued = false;
    let pendingRebuild = false;
    let pendingRestart = false;
    let pendingNative = false;
    let latestChange = "";
    let requestedRevision = 0;
    let lastChangeAt = 0;
    let cancellationPromise;

    const scheduleAfterQuietPeriod = () => {
      clearTimeout(debounceTimer);
      const quietFor = Date.now() - lastChangeAt;
      const delay = Math.max(100, 300 - quietFor);
      debounceTimer = setTimeout(() => void runPendingCapture(), delay);
    };

    const runPendingCapture = async () => {
      if (running) {
        queued = true;
        return;
      }
      running = true;
      queued = false;
      const rebuild = pendingRebuild;
      let restart = pendingRestart;
      const native = pendingNative;
      const change = latestChange;
      const revision = requestedRevision;
      pendingRebuild = false;
      pendingRestart = false;
      pendingNative = false;
      const startedAt = Date.now();
      const requireLatestRevision = () => {
        if (revision !== requestedRevision) {
          throw new CaptureSupersededError(latestChange);
        }
      };
      console.log(
        `\nChange detected${change ? `: ${change}` : ""}. ` +
          `${
            native
              ? "Rebuilding the native app and capturing"
              : rebuild
                ? "Rebundling and capturing"
                : "Recapturing"
          }…`,
      );
      setVisualCatalogStatus("capturing", {
        message: native
          ? "Rebuilding native app and recapturing"
          : rebuild
            ? "Rebuilding and recapturing"
            : "Recapturing screenshots",
        detail: change || "Running the simulator shards",
        startedAt: new Date(startedAt).toISOString(),
      });
      try {
        if (cancellationPromise) await cancellationPromise;
        requireLatestRevision();
        await assertHarnessBoundary();
        manifest = await loadManifest();
        if (manifest.appId !== session.appId) {
          throw new Error(
            "The visual appId changed. Restart watch mode before continuing.",
          );
        }
        restart ||= !processes.isHealthy();
        if (rebuild) {
          await installVisualApp(
            { ...options, cleanNative: native, skipBuild: false },
            session,
            manifest,
          );
          requireLatestRevision();
        }
        if (restart) {
          await processes.stop();
          requireLatestRevision();
        }
        const cycle = await bridge.beginCycle(manifest);
        requireLatestRevision();
        const syncedFlows = await syncWatchFlows(manifest);
        requireLatestRevision();
        if (restart) {
          processes = startContinuousMaestro(
            session,
            manifest,
            syncedFlows.flowPaths,
            bridge,
          );
        } else {
          const unchangedShards = session.simulators
            .map((_simulator, index) => index)
            .filter((index) => !syncedFlows.changedShards.includes(index));
          processes.trigger(unchangedShards);
        }
        await cycle.completion;
        requireLatestRevision();
        const warning = reportShotDrift(cycle.seen, manifest);
        setVisualCatalogStatus("ready", {
          message: "Screenshots are up to date",
          detail: warning || `${((Date.now() - startedAt) / 1000).toFixed(1)}s`,
        });
        console.log(
          `\nCatalog refreshed in ${((Date.now() - startedAt) / 1000).toFixed(1)}s.`,
        );
      } catch (error) {
        if (error instanceof CaptureSupersededError) {
          console.log(`\nCapture cancelled: ${error.message}.`);
        } else {
          setVisualCatalogStatus("error", {
            message: "Screenshot refresh failed",
            detail: error.message,
          });
          console.error(`\nWatch capture failed: ${error.message}`);
          console.error(
            "Fix the error and save again; the watcher is still running.",
          );
        }
      } finally {
        running = false;
        if (queued || pendingRebuild || pendingRestart || pendingNative) {
          scheduleAfterQuietPeriod();
        }
      }
    };

    const scheduleCapture = (rebuild, restart, native, changedPath) => {
      if (shouldIgnoreWatchPath(changedPath)) return;
      pendingRebuild ||= rebuild;
      pendingRestart ||= restart;
      pendingNative ||= native;
      latestChange = path.relative(repositoryRoot, changedPath);
      requestedRevision += 1;
      lastChangeAt = Date.now();
      if (running) {
        queued = true;
        pendingRestart = true;
        bridge.cancel(latestChange);
        setVisualCatalogStatus("capturing", {
          message: "Restarting with latest edits",
          detail: latestChange,
          startedAt: new Date(lastChangeAt).toISOString(),
        });
        if (!cancellationPromise) {
          cancellationPromise = processes.stop().finally(() => {
            cancellationPromise = undefined;
          });
        }
      }
      scheduleAfterQuietPeriod();
    };

    const observedFingerprints = new Map(startupFingerprints);
    const fingerprintChecks = new Map();
    const scheduleChangedTarget = (watchTarget, changedPath) => {
      const previousCheck = fingerprintChecks.get(watchTarget.target);
      const check = (previousCheck ?? Promise.resolve())
        .catch(() => undefined)
        .then(async () => {
          const fingerprint = (
            await watchTargetFingerprints([watchTarget])
          ).get(watchTarget.target);
          if (fingerprint === observedFingerprints.get(watchTarget.target)) {
            return;
          }
          observedFingerprints.set(watchTarget.target, fingerprint);
          scheduleCapture(
            watchTarget.rebuild,
            watchTarget.restart,
            watchTarget.native,
            changedPath,
          );
        })
        .catch((error) => {
          console.error(
            `Could not inspect visual watch change for ${watchTarget.target}: ${error.message}`,
          );
        })
        .finally(() => {
          if (fingerprintChecks.get(watchTarget.target) === check) {
            fingerprintChecks.delete(watchTarget.target);
          }
        });
      fingerprintChecks.set(watchTarget.target, check);
    };

    watchers = targets.map((watchTarget) => {
      const { target, recursive } = watchTarget;
      return watchPath(target, { recursive }, (_event, filename) => {
        const changedPath = filename
          ? path.resolve(
              recursive ? target : path.dirname(target),
              filename.toString(),
            )
          : target;
        scheduleChangedTarget(
          watchTarget,
          watchChangePath(target, changedPath),
        );
      });
    });

    const currentFingerprints = await watchTargetFingerprints(targets);
    for (const { target, rebuild, restart, native } of targets) {
      const fingerprint = currentFingerprints.get(target);
      if (fingerprint === observedFingerprints.get(target)) {
        continue;
      }
      observedFingerprints.set(target, fingerprint);
      scheduleCapture(rebuild, restart, native, target);
    }

    console.log(
      `\nPersistent watch is ready across ${targets.length} source locations. ` +
        "Save a file to refresh all screenshots.",
    );
    await serveCatalog(options.port, options.open);
  } finally {
    clearTimeout(debounceTimer);
    for (const watcher of watchers) watcher.close();
    if (processes) await processes.stop();
    if (bridge) await bridge.close();
    await closeCaptureSession(session);
  }
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  setGentleMode(options.gentle);
  if (options.command === "serve") {
    await serveCatalog(options.port, options.open);
    return;
  }
  if (options.command === "watch") {
    await watchCatalog(options);
    return;
  }
  await capture(options);
}

const invokedAsScript =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedAsScript) {
  main().catch((error) => {
    console.error(`\nVisual catalog failed: ${error.message}`);
    process.exitCode = 1;
  });
}
