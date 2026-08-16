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
export const androidMaestroDirectory = path.join(
  androidVisualDirectory,
  "maestro",
);
export const androidCaptureScreenshotsDirectory = path.join(
  androidVisualDirectory,
  "capture/screenshots",
);
const screenshotsDirectory = path.join(visualDirectory, "screenshots");
const captureScreenshotsDirectory = path.join(
  visualDirectory,
  "capture/screenshots",
);
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
const watchDirectory = path.join(visualDirectory, "watch");
const watchFlowsDirectory = path.join(watchDirectory, "flows");
const watchScreenshotsDirectory = path.join(watchDirectory, "screenshots");
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
let visualCatalogStatus = {
  state: "ready",
  message: "Screenshots are up to date",
  detail: "",
  startedAt: null,
  updatedAt: new Date().toISOString(),
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
    updatedAt: new Date().toISOString(),
  };
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
  capture       Build, capture, generate, and serve the catalog (default)
  serve         Serve the most recently generated catalog
  watch         Capture, watch code, and refresh the catalog after edits

Options:
  --device <name-or-udid>  Simulator to use
  --show-simulator         Open Simulator.app while capturing
  --skip-build             Skip even the fast JavaScript rebundle
  --clean-native           Regenerate the cached native iOS project
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
  return options;
}

export function run(command, argumentsList, options = {}) {
  const shown = [command, ...argumentsList]
    .map((value) => (value.includes(" ") ? JSON.stringify(value) : value))
    .join(" ");
  if (!options.quiet) console.log(`\n› ${shown}`);
  return new Promise((resolve, reject) => {
    const child = spawn(command, argumentsList, {
      cwd: options.cwd ?? mobileRoot,
      env: { ...process.env, ...options.env },
      stdio: options.capture ? ["ignore", "pipe", "pipe"] : "inherit",
    });
    let stdout = "";
    let stderr = "";
    if (options.capture) {
      child.stdout.on("data", (chunk) => {
        stdout += chunk;
      });
      child.stderr.on("data", (chunk) => {
        stderr += chunk;
      });
    }
    child.on("error", reject);
    child.on("exit", (code, signal) => {
      if (code === 0 || options.allowFailure) {
        resolve({ code, signal, stdout, stderr });
        return;
      }
      const detail = [stdout.trim(), stderr.trim()].filter(Boolean).join("\n");
      reject(
        new Error(
          `${command} exited with ${code ?? signal}.${detail ? `\n${detail}` : ""}`,
        ),
      );
    });
  });
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

const scenarioPlatforms = ["ios", "android"];

export function scenarioOnPlatform(scenario, platform) {
  return !Array.isArray(scenario.platforms) ||
    scenario.platforms.includes(platform);
}

export async function loadManifest(platform = "ios") {
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  if (manifest.version !== 1) {
    throw new Error(`Unsupported visual manifest version: ${manifest.version}`);
  }
  if (typeof manifest.appId !== "string" || !manifest.appId) {
    throw new Error("The visual manifest must define appId.");
  }
  if (!Array.isArray(manifest.flows) || manifest.flows.length < shardCount) {
    throw new Error(
      `The visual manifest must define at least ${shardCount} flows so every shard has work.`,
    );
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

  for (let index = 1; index <= shardCount; index += 1) {
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
  await rm(captureScreenshotsDirectory, { recursive: true, force: true });
  await rm(maestroDirectory, { recursive: true, force: true });
  await mkdir(captureScreenshotsDirectory, { recursive: true });
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
      { cwd: mobileRoot, env: tools.environment },
    );
    await cycle.completion;
  } catch (error) {
    bridge.fail(error);
    await cycle.completion.catch(() => {});
    throw error;
  } finally {
    await bridge.close();
  }
  await Promise.all(
    manifest.scenarios.map((scenario) =>
      copyFile(
        path.join(watchScreenshotsDirectory, scenario.screenshot),
        path.join(captureScreenshotsDirectory, scenario.screenshot),
      ),
    ),
  );
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

function scenarioCaptures(scenario) {
  return (
    scenario.captures ?? [
      {
        platform: "",
        captured: scenario.captured,
        image: scenario.image,
        size: scenario.size,
        missingLabel: scenario.missingLabel,
        expected: scenario.expected ?? true,
      },
    ]
  );
}

function captureShotHtml(scenario, capture, defaultPlatform) {
  const subject = capture.platform
    ? `${scenario.title} on ${capture.platform}`
    : scenario.title;
  const livePlatform = (capture.platform || defaultPlatform).toLowerCase();
  return `
          <div class="shot" data-screenshot="${escapeHtml(
            scenario.screenshot,
          )}" data-live-platform="${livePlatform}" data-expected="${
            capture.expected === false ? "false" : "true"
          }" data-scenario-id="${escapeHtml(scenario.id ?? "")}" data-group="${escapeHtml(
            scenario.group ?? "",
          )}" data-title="${escapeHtml(scenario.title)}">
            <button class="preview"${
              capture.captured
                ? ` data-image="${escapeHtml(capture.image)}"`
                : ""
            } aria-label="Open ${escapeHtml(subject)}">
              <span class="device-screen"${
                capture.size
                  ? ` style="--shot-ratio: ${capture.size.width} / ${capture.size.height}"`
                  : ""
              }>
                ${
                  capture.captured
                    ? `<img src="${escapeHtml(capture.image)}" alt="${escapeHtml(
                        subject,
                      )}" loading="lazy">`
                    : `<span class="missing">${escapeHtml(
                        capture.missingLabel ?? "Screenshot missing",
                      )}</span>`
                }
              </span>
            </button>
            <div class="shot-meta">
              ${
                capture.platform
                  ? `<span class="platform-tag">${escapeHtml(capture.platform)}</span>`
                  : ""
              }
              <button class="copy-ref" type="button" aria-label="Copy reference for ${escapeHtml(
                subject,
              )}">Copy ref</button>
            </div>
          </div>`;
}

export function galleryHtml(catalog) {
  const catalogJson = JSON.stringify(catalog).replaceAll("<", "\\u003c");
  const defaultPlatform = catalog.platform === "android" ? "android" : "ios";
  const scenarioGroups = new Map();
  let platformColumns = 1;
  for (const scenario of catalog.scenarios) {
    const group = scenario.group || "Other";
    const scenarios = scenarioGroups.get(group) ?? [];
    scenarios.push(scenario);
    scenarioGroups.set(group, scenarios);
    platformColumns = Math.max(platformColumns, scenarioCaptures(scenario).length);
  }
  const sections = [...scenarioGroups.entries()]
    .map(([group, scenarios], sectionIndex) => {
      const cards = scenarios
        .map((scenario) => {
          const captures = scenarioCaptures(scenario);
          return `
        <article class="card">
          <div class="shots" style="--shots: ${captures.length}">${captures
            .map((capture) => captureShotHtml(scenario, capture, defaultPlatform))
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
        </article>`;
        })
        .join("");
      const sectionId = `scenario-section-${sectionIndex}`;
      return `
    <section class="scenario-section" aria-labelledby="${sectionId}">
      <div class="section-header">
        <h2 class="section-title" id="${sectionId}">${escapeHtml(group)}</h2>
        <span class="section-count">${scenarios.length} ${
          scenarios.length === 1 ? "screen" : "screens"
        }</span>
      </div>
      <div class="grid">${cards}</div>
    </section>`;
    })
    .join("");
  const deviceChips = (
    catalog.platforms
      ? catalog.platforms.map(
          (platform) =>
            `${platform.label} · ${platform.device.name} · ${platform.device.runtime}`,
        )
      : [catalog.device.name, catalog.device.runtime]
  )
    .map((chip) => `<span>${escapeHtml(chip)}</span>`)
    .join("\n      ");
  const reportLinks = (
    catalog.platforms
      ? catalog.platforms
          .filter((platform) => platform.reportAvailable)
          .map((platform) => ({
            label: `${platform.label} Maestro report`,
            href: platform.reportHref,
          }))
      : catalog.reportAvailable
        ? [{ label: "Maestro report", href: "maestro/report.html" }]
        : []
  )
    .map(
      (link) =>
        `<a class="report" href="${escapeHtml(link.href)}">${escapeHtml(link.label)}</a>`,
    )
    .join("\n      ");
  const scanPlatforms = catalog.platforms
    ? catalog.platforms.map((platform) => ({
        key: platform.label.toLowerCase(),
        label: platform.label,
        generatedAt: platform.generatedAt ?? catalog.generatedAt,
      }))
    : [
        {
          key: defaultPlatform,
          label: defaultPlatform === "android" ? "Android" : "iOS",
          generatedAt: catalog.generatedAt,
        },
      ];
  const scanRows = scanPlatforms
    .map(
      (platform) => `
    <div class="scan-row" data-platform="${platform.key}">
      <span class="scan-platform">${escapeHtml(platform.label)}</span>
      <span class="scan-last" data-generated-at="${escapeHtml(
        platform.generatedAt,
      )}">last scan</span>
      <span class="scan-progress" hidden></span>
      <button class="scan-button" type="button">Scan</button>
    </div>`,
    )
    .join("");

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vesta mobile visual catalog</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0c0c0f;
      --card: #17171c;
      --border: #2b2b33;
      --muted: #9898a5;
      --text: #f4f4f6;
      --accent: #b8a7ff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at 50% -30%, #30245e 0, transparent 34rem),
        var(--bg);
      color: var(--text);
      font: 14px/1.45 ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
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
    .kicker {
      color: var(--accent);
      font-size: 10px;
      font-weight: 700;
      letter-spacing: .12em;
      text-transform: uppercase;
    }
    h1 {
      margin: 4px 0 5px;
      font-size: clamp(28px, 4vw, 42px);
      line-height: 1;
      letter-spacing: -.045em;
    }
    .intro { margin: 0; color: var(--muted); font-size: 14px; }
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
      background: #111116cc;
      color: var(--muted);
      text-decoration: none;
      font-size: 10px;
    }
    .report:hover { color: var(--text); border-color: #555563; }
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
      background: #111116cc;
      color: var(--muted);
      font-size: 11px;
    }
    .scan-platform { color: var(--text); font-weight: 700; }
    .scan-progress { color: var(--accent); font-weight: 700; }
    .scan-row[data-state="failed"] .scan-last { color: #ee6673; }
    .scan-button {
      border: 1px solid #625799;
      border-radius: 999px;
      padding: 4px 13px;
      background: #241f38;
      color: var(--text);
      font-size: 11px;
      cursor: pointer;
    }
    .scan-button:hover:not(:disabled) { border-color: var(--accent); }
    .scan-button:disabled { opacity: .55; cursor: default; }
    main {
      max-width: 1680px;
      margin: 0 auto;
      padding: 8px 24px 64px;
    }
    .scenario-section + .scenario-section { margin-top: 48px; }
    .section-header {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 10px;
    }
    .section-title {
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
      letter-spacing: -.025em;
    }
    .section-count {
      flex: 0 0 auto;
      color: var(--muted);
      font-size: 11px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(min(100%, 210px), 1fr));
      align-items: start;
      gap: 16px;
    }
    body[data-platforms="2"] .grid {
      grid-template-columns: repeat(auto-fill, minmax(min(100%, 380px), 1fr));
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
    .shot.pending .device-screen::after {
      content: "";
      position: absolute;
      top: 50%;
      left: 50%;
      width: 26px;
      height: 26px;
      margin: -13px 0 0 -13px;
      border: 3px solid #b8a7ff35;
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: status-spin .8s linear infinite;
    }
    .shot.pending .device-screen img { opacity: .35; }
    .shot.pending .missing { visibility: hidden; }
    .shot.fresh .preview { border-color: #7f6fd4; }
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
      border: 1px solid #625799;
      border-radius: 999px;
      padding: 9px 14px 9px 10px;
      background: #181522f2;
      box-shadow: 0 12px 40px #0009, inset 0 0 0 1px #ffffff0d;
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
      border-color: #a84952;
      background: #28161af2;
    }
    .status-spinner {
      width: 25px;
      height: 25px;
      flex: 0 0 auto;
      border: 3px solid #b8a7ff35;
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: status-spin .8s linear infinite;
    }
    .capture-status[data-state="error"] .status-spinner {
      display: grid;
      border: 0;
      background: #ee6673;
      color: #21070a;
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
    .missing { color: var(--muted); }
    .card-copy {
      margin-top: 9px;
      border: 1px solid var(--border);
      border-radius: 13px;
      padding: 11px 12px 12px;
      background: linear-gradient(150deg, #1b1b21, var(--card));
      box-shadow: 0 8px 24px #0003;
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
<body data-platforms="${platformColumns}">
  <div class="capture-status" id="capture-status" data-state="ready" role="status" aria-live="polite" hidden>
    <span class="status-spinner" aria-hidden="true"></span>
    <span class="status-copy">
      <strong class="status-title">Recapturing screenshots</strong>
      <span class="status-detail">Running both simulator shards…</span>
    </span>
  </div>
  <header>
    <div>
      <span class="kicker">Mobile QA</span>
      <h1>Visual catalog</h1>
      <p class="intro">Complete device captures at a glance. Click any image to expand it.</p>
    </div>
    <div class="meta">
      ${deviceChips}
      <span>${escapeHtml(catalog.generatedAt)}</span>
      <span>${escapeHtml(catalog.git.revision)}${catalog.git.dirty ? " · dirty" : ""}</span>
      ${reportLinks}
    </div>
  </header>
  <section class="scan-bar" aria-label="Capture runs">${scanRows}
  </section>
  <main>${sections}</main>
  <dialog id="lightbox">
    <button aria-label="Close">×</button>
    <img alt="">
  </dialog>
  <script>
    window.__VISUAL_CATALOG__ = ${catalogJson};
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
        "catalog: " + window.__VISUAL_CATALOG__.generatedAt +
          " | rev: " + window.__VISUAL_CATALOG__.git.revision,
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
            " [" + shot.dataset.livePlatform + "]",
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
            (shot) => shot.dataset.livePlatform + ": " + shotImage(shot),
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
        const context = nextStatus.detail || "Running both simulator shards";
        statusDetail.textContent = context + " · " + elapsed + "s";
      } else if (state === "error") {
        statusTitle.textContent = nextStatus.message || "Screenshot refresh failed";
        statusDetail.textContent = nextStatus.detail || "Fix the issue and save again.";
      }
    }
    const generatedAt = window.__VISUAL_CATALOG__.generatedAt;
    const publishedMs = Date.parse(generatedAt);
    function formatScanTime(iso) {
      const ms = Date.parse(iso ?? "");
      if (Number.isNaN(ms)) return "never";
      return new Date(ms).toLocaleString();
    }
    document.querySelectorAll(".scan-row").forEach((row) => {
      const last = row.querySelector(".scan-last");
      last.textContent = "last scan " + formatScanTime(last.dataset.generatedAt);
      const button = row.querySelector(".scan-button");
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await fetch("capture/" + row.dataset.platform, { method: "POST" });
        } catch {
          button.disabled = false;
        }
      });
    });
    function updateScanRows(runs, freshCounts) {
      document.querySelectorAll(".scan-row").forEach((row) => {
        const platform = row.dataset.platform;
        const run = (runs ?? {})[platform];
        const running = Boolean(run && run.running);
        const button = row.querySelector(".scan-button");
        const progress = row.querySelector(".scan-progress");
        button.disabled = running;
        button.textContent = running ? "Scanning" : "Scan";
        const total = document.querySelectorAll(
          '.shot[data-live-platform="' + platform + '"][data-expected="true"]',
        ).length;
        const fresh = freshCounts[platform] ?? 0;
        progress.hidden = !running && fresh === 0;
        progress.textContent = fresh + "/" + total;
        const failed = Boolean(run && !running && run.exitCode);
        row.dataset.state = failed ? "failed" : "ok";
        if (failed) {
          row.querySelector(".scan-last").textContent =
            "last scan failed, see capture-" + platform + ".log";
        }
      });
    }
    function applyLive(live) {
      let active = false;
      const freshCounts = { ios: 0, android: 0 };
      for (const platform of ["ios", "android"]) {
        for (const entry of Object.values(live[platform] ?? {})) {
          if (entry.mtime > publishedMs) active = true;
        }
      }
      document.querySelectorAll(".shot[data-screenshot]").forEach((shot) => {
        if (shot.dataset.expected === "false") return;
        const platformEntries = live[shot.dataset.livePlatform] ?? {};
        const entry = platformEntries[shot.dataset.screenshot];
        const fresh = Boolean(entry && entry.mtime > publishedMs);
        if (fresh) freshCounts[shot.dataset.livePlatform] += 1;
        shot.classList.toggle("pending", active && !fresh);
        shot.classList.toggle("fresh", fresh);
        if (!fresh) return;
        const button = shot.querySelector(".preview");
        const screen = shot.querySelector(".device-screen");
        let image = screen.querySelector("img");
        if (!image) {
          screen.textContent = "";
          image = document.createElement("img");
          image.alt = shot.dataset.screenshot;
          screen.appendChild(image);
        }
        const stamp = String(entry.mtime);
        if (image.dataset.liveStamp !== stamp) {
          const src = entry.src + "?v=" + stamp;
          image.src = src;
          image.dataset.liveStamp = stamp;
          button.dataset.image = src;
        }
      });
      return freshCounts;
    }
    window.setInterval(async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const [iosResponse, androidResponse, statusResponse, liveResponse] =
          await Promise.all([
            fetch("catalog.json", { cache: "no-store" }),
            fetch("android/catalog.json", { cache: "no-store" }),
            fetch("status.json", { cache: "no-store" }),
            fetch("live.json", { cache: "no-store" }),
          ]);
        if (statusResponse.ok) showCaptureStatus(await statusResponse.json());
        if (liveResponse.ok) {
          const live = await liveResponse.json();
          updateScanRows(live.runs, applyLive(live));
        }
        const stamps = [];
        for (const response of [iosResponse, androidResponse]) {
          if (response.ok) stamps.push((await response.json()).generatedAt);
        }
        if (stamps.length === 0) return;
        const newest = stamps.sort().at(-1);
        if (newest !== generatedAt) window.location.reload();
      } catch {
        // The local server may be between restarts.
      }
    }, 500);
  </script>
</body>
</html>`;
}

function platformCapture(label, scenario, imagePrefix) {
  return {
    platform: label,
    captured: scenario.captured,
    image: scenario.image ? `${imagePrefix}${scenario.image}` : "",
    size: scenario.size ?? null,
    missingLabel: scenario.captured
      ? undefined
      : (scenario.missingLabel ?? "Not captured yet"),
    expected: scenario.expected ?? true,
  };
}

function missingCapture(label) {
  return {
    platform: label,
    captured: false,
    image: "",
    size: null,
    missingLabel: "Not captured yet",
    expected: true,
  };
}

export function unifiedCatalog(iosCatalog, androidCatalog) {
  if (!iosCatalog || !androidCatalog) return iosCatalog ?? androidCatalog ?? null;
  const androidById = new Map(
    androidCatalog.scenarios.map((scenario) => [scenario.id, scenario]),
  );
  const scenarios = iosCatalog.scenarios.map((scenario) => {
    const android = androidById.get(scenario.id);
    return {
      ...scenario,
      captures: [
        platformCapture("iOS", scenario, ""),
        android
          ? platformCapture("Android", android, "android/")
          : missingCapture("Android"),
      ],
    };
  });
  const iosIds = new Set(iosCatalog.scenarios.map((scenario) => scenario.id));
  for (const scenario of androidCatalog.scenarios) {
    if (iosIds.has(scenario.id)) continue;
    scenarios.push({
      ...scenario,
      captures: [
        missingCapture("iOS"),
        platformCapture("Android", scenario, "android/"),
      ],
    });
  }
  const newest =
    Date.parse(androidCatalog.generatedAt) > Date.parse(iosCatalog.generatedAt)
      ? androidCatalog
      : iosCatalog;
  return {
    ...iosCatalog,
    generatedAt: newest.generatedAt,
    git: newest.git,
    platforms: [
      {
        label: "iOS",
        device: iosCatalog.device,
        generatedAt: iosCatalog.generatedAt,
        reportAvailable: iosCatalog.reportAvailable === true,
        reportHref: "maestro/report.html",
      },
      {
        label: "Android",
        device: androidCatalog.device,
        generatedAt: androidCatalog.generatedAt,
        reportAvailable: androidCatalog.reportAvailable === true,
        reportHref: "android/maestro/report.html",
      },
    ],
    scenarios,
  };
}

async function storedCatalog(directory) {
  const file = path.join(directory, "catalog.json");
  if (!(await exists(file))) return null;
  return JSON.parse(await readFile(file, "utf8"));
}

const LIVE_CAPTURE_ROOTS = [
  { platform: "ios", directory: watchScreenshotsDirectory },
  { platform: "ios", directory: captureScreenshotsDirectory },
  { platform: "android", directory: androidCaptureScreenshotsDirectory },
  { platform: "android", directory: androidMaestroDirectory, maestro: true },
];

// Index of in-progress capture screenshots: platform -> filename -> newest
// file, with src relative to the gallery root so the page can load it live.
export async function liveCaptureEntries(
  roots = LIVE_CAPTURE_ROOTS,
  baseDirectory = visualDirectory,
) {
  const entries = { ios: {}, android: {} };
  const record = async (platform, file) => {
    const name = path.basename(file);
    const mtime = Math.round((await stat(file)).mtimeMs);
    const existing = entries[platform][name];
    if (existing && existing.mtime >= mtime) return;
    entries[platform][name] = {
      src: path.relative(baseDirectory, file).split(path.sep).join("/"),
      mtime,
    };
  };
  for (const root of roots) {
    if (!(await exists(root.directory))) continue;
    if (root.maestro) {
      for (const file of await filesBelow(root.directory)) {
        if (!file.endsWith(".png")) continue;
        if (path.basename(path.dirname(file)) !== "takeScreenshot") continue;
        await record(root.platform, file);
      }
      continue;
    }
    for (const entry of await readdir(root.directory)) {
      if (!entry.endsWith(".png")) continue;
      await record(root.platform, path.join(root.directory, entry));
    }
  }
  return entries;
}

export async function composedCatalog(overrides = {}) {
  const ios =
    "ios" in overrides ? overrides.ios : await storedCatalog(visualDirectory);
  const android =
    "android" in overrides
      ? overrides.android
      : await storedCatalog(androidVisualDirectory);
  return unifiedCatalog(ios, android);
}

export async function writeUnifiedIndex(overrides = {}) {
  const catalog = await composedCatalog(overrides);
  if (!catalog) return;
  await atomicWriteFile(
    path.join(visualDirectory, "index.html"),
    galleryHtml(catalog),
  );
}

async function cleanupScreenshotReleases(activeRelease) {
  const entries = await readdir(screenshotsDirectory, { withFileTypes: true });
  const releases = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const target = path.join(screenshotsDirectory, entry.name);
    releases.push({ name: entry.name, modified: (await stat(target)).mtimeMs });
  }
  releases.sort((left, right) => right.modified - left.modified);
  const keep = new Set([
    activeRelease,
    ...releases
      .filter((release) => release.name !== activeRelease)
      .slice(0, 2)
      .map((release) => release.name),
  ]);
  await Promise.all(
    releases
      .filter((release) => !keep.has(release.name))
      .map((release) =>
        rm(path.join(screenshotsDirectory, release.name), {
          recursive: true,
          force: true,
        }),
      ),
  );
}

async function prepareGalleryPublication(
  manifest,
  simulators,
  sourceDirectory,
  options = {},
) {
  temporaryFileCounter += 1;
  const release = `${Date.now()}-${process.pid}-${temporaryFileCounter}`;
  const releaseDirectory = path.join(screenshotsDirectory, release);
  await mkdir(releaseDirectory, { recursive: true });
  await Promise.all(
    manifest.scenarios.map((scenario) =>
      copyFile(
        path.join(sourceDirectory, scenario.screenshot),
        path.join(releaseDirectory, scenario.screenshot),
      ),
    ),
  );

  const git = await gitMetadata();
  const scenarios = [];
  for (const scenario of manifest.scenarios) {
    const screenshot = path.join(releaseDirectory, scenario.screenshot);
    const captured = await exists(screenshot);
    const size = captured ? await pngSize(screenshot) : null;
    scenarios.push({
      ...scenario,
      captured,
      image: `screenshots/${release}/${scenario.screenshot}`,
      size,
    });
  }
  const invalid = scenarios.filter(
    (scenario) => !scenario.captured || !scenario.size,
  );
  if (invalid.length > 0) {
    throw new Error(
      `Missing or invalid screenshots: ${invalid
        .map((scenario) => scenario.screenshot)
        .join(", ")}`,
    );
  }

  const catalog = {
    generatedAt: new Date().toISOString(),
    appId: manifest.appId,
    mode: options.mode ?? "capture",
    reportAvailable: options.reportAvailable === true,
    device: {
      name: `${simulators.length} × ${simulators[0].name
        .replace(/^Vesta Visual \d+ — /, "")
        .replace(/ \(.+\)$/, "")}`,
      udid: simulators.map((simulator) => simulator.udid).join(","),
      runtime: simulators[0].runtimeName,
    },
    git,
    scenarios,
  };
  const catalogPath = path.join(visualDirectory, "catalog.json");
  const indexPath = path.join(visualDirectory, "index.html");
  const catalogTemporary = `${catalogPath}.${release}.tmp`;
  const indexTemporary = `${indexPath}.${release}.tmp`;
  await writeFile(catalogTemporary, `${JSON.stringify(catalog, null, 2)}\n`);
  await writeFile(
    indexTemporary,
    galleryHtml(await composedCatalog({ ios: catalog })),
  );

  return {
    catalog,
    async commit(validate = () => {}) {
      await validate();
      await rename(indexTemporary, indexPath);
      await validate();
      await rename(catalogTemporary, catalogPath);
      try {
        await cleanupScreenshotReleases(release);
      } catch (error) {
        console.warn(`Could not prune old screenshot releases: ${error.message}`);
      }
      return catalog;
    },
  };
}

async function publishGallery(
  manifest,
  simulators,
  sourceDirectory,
  options = {},
) {
  await mkdir(screenshotsDirectory, { recursive: true });
  const publication = await prepareGalleryPublication(
    manifest,
    simulators,
    sourceDirectory,
    options,
  );
  return publication.commit(options.validate);
}

async function markCatalogAsWatchMode() {
  const catalogPath = path.join(visualDirectory, "catalog.json");
  if (!(await exists(catalogPath))) return;
  const catalog = JSON.parse(await readFile(catalogPath, "utf8"));
  if (catalog.mode === "watch" && catalog.reportAvailable === false) return;
  const watchCatalog = {
    ...catalog,
    generatedAt: new Date().toISOString(),
    mode: "watch",
    reportAvailable: false,
  };
  await atomicWriteFile(
    path.join(visualDirectory, "index.html"),
    galleryHtml(await composedCatalog({ ios: watchCatalog })),
  );
  await atomicWriteFile(
    catalogPath,
    `${JSON.stringify(watchCatalog, null, 2)}\n`,
  );
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
  await writeUnifiedIndex();
  if (!(await exists(path.join(baseDirectory, "index.html")))) {
    throw new Error("No visual catalog exists yet. Run the capture command first.");
  }
  const idleRun = { running: false, startedAt: null, finishedAt: null, exitCode: null };
  const captureRuns = { ios: { ...idleRun }, android: { ...idleRun } };
  const captureScripts = {
    ios: fileURLToPath(import.meta.url),
    android: path.join(mobileRoot, "scripts/visual-catalog-android.mjs"),
  };
  const startCaptureRun = (platform) => {
    if (captureRuns[platform].running) return false;
    const logFile = openSync(
      path.join(visualDirectory, `capture-${platform}.log`),
      "w",
    );
    const child = spawn(
      process.execPath,
      [captureScripts[platform], "capture", "--no-serve", "--no-open"],
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
      response.end(`${JSON.stringify(visualCatalogStatus)}\n`);
      return;
    }
    if (pathname === "/live.json") {
      response.writeHead(200, {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
      });
      response.end(
        `${JSON.stringify({ ...(await liveCaptureEntries()), runs: captureRuns })}\n`,
      );
      return;
    }
    if (pathname === "/capture/ios" || pathname === "/capture/android") {
      const platform = pathname.split("/")[2];
      if (request.method !== "POST") {
        response.writeHead(405).end("POST required");
        return;
      }
      const started = startCaptureRun(platform);
      response.writeHead(started ? 202 : 409, {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
      });
      response.end(`${JSON.stringify({ started, run: captureRuns[platform] })}\n`);
      return;
    }
    if (pathname === "/" || pathname === "/index.html") {
      try {
        const catalog = await composedCatalog();
        if (!catalog) throw new Error("no catalog");
        response.writeHead(200, {
          "Content-Type": "text/html; charset=utf-8",
          "Cache-Control": "no-store",
        });
        response.end(galleryHtml(catalog));
      } catch {
        response.writeHead(404).end("No visual catalog exists yet.");
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

async function runCaptureIteration(options, session) {
  await assertHarnessBoundary();
  const manifest = await loadManifest();
  if (manifest.appId !== session.appId) {
    throw new Error(
      "The visual appId changed. Restart the capture command before continuing.",
    );
  }
  await installVisualApp(options, session, manifest);
  await runMaestro(manifest, session.simulators, session.tools);
  const catalog = await publishGallery(
    manifest,
    session.simulators,
    captureScreenshotsDirectory,
    {
      mode: "capture",
      reportAvailable: await exists(path.join(maestroDirectory, "report.html")),
    },
  );
  console.log(`\nCaptured ${catalog.scenarios.length} mobile screenshots.`);
  return catalog;
}

async function installVisualApp(options, session, manifest) {
  const { simulators } = session;
  if (options.skipBuild) {
    await Promise.all(
      simulators.map((simulator) =>
        requireInstalledApp(simulator.udid, manifest.appId),
      ),
    );
  } else {
    if (options.cleanNative) {
      await rm(nativeIosDirectory, { recursive: true, force: true });
      await rm(nativeFingerprintPath, { force: true });
    }
    await buildAndInstall(simulators, manifest.appId);
  }
}

async function closeCaptureSession(session) {
  await Promise.all(
    session.simulators.map((simulator, index) =>
      restoreSimulator(simulator.udid, session.previousUi[index]),
    ),
  );
}

async function capture(options) {
  const session = await prepareCaptureSession(options);
  try {
    await runCaptureIteration(options, session);
  } finally {
    await closeCaptureSession(session);
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
        !cycle.expected.has(screenshot) ||
        path.basename(screenshot) !== screenshot
      ) {
        throw new Error(`Unexpected screenshot: ${screenshot}`);
      }
      await run(
        "xcrun",
        [
          "simctl",
          "io",
          simulator.udid,
          "screenshot",
          "--type=png",
          path.join(watchScreenshotsDirectory, screenshot),
        ],
        { capture: true, quiet: true },
      );
      cycle.seen.add(screenshot);
      response.writeHead(204).end();
      if (cycle.seen.size === cycle.expected.size) {
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
      await rm(watchScreenshotsDirectory, { recursive: true, force: true });
      await mkdir(watchScreenshotsDirectory, { recursive: true });
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
      return { completion };
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

async function publishWatchScreenshots(manifest, simulators, validate) {
  const catalog = await publishGallery(
    manifest,
    simulators,
    watchScreenshotsDirectory,
    { mode: "watch", reportAvailable: false, validate },
  );
  console.log(`\nCaptured ${catalog.scenarios.length} mobile screenshots.`);
  return catalog;
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
  await markCatalogAsWatchMode();
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
      await publishWatchScreenshots(manifest, session.simulators);
      setVisualCatalogStatus("ready", {
        message: "Screenshots are up to date",
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
        detail: change || "Running both simulator shards",
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
        await publishWatchScreenshots(
          manifest,
          session.simulators,
          requireLatestRevision,
        );
        requireLatestRevision();
        setVisualCatalogStatus("ready", {
          message: "Screenshots are up to date",
          detail: `${((Date.now() - startedAt) / 1000).toFixed(1)}s`,
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
