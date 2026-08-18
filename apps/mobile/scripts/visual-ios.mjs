#!/usr/bin/env node
// iOS visual runner: builds the isolated visual app, drives it with Maestro on
// two simulator shards, and writes each shot into the shared visual store.

import { existsSync } from "node:fs";
import { createServer } from "node:http";
import {
  copyFile,
  mkdir,
  readFile,
  readdir,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { fileURLToPath } from "node:url";
import os from "node:os";
import path from "node:path";
import { loadRegistry, scenariosForPlatform } from "@vesta/visual/registry";
import { publishRunStatus } from "@vesta/visual/run-status";
import { putShot, shotDriftWarning } from "@vesta/visual/store";
import {
  activeShardCount,
  assertHarnessBoundary,
  atomicWriteFile,
  createInactivityWatchdog,
  exists,
  filesBelow,
  flowFailureError,
  jsBundleCurrent,
  mobileRoot,
  nativeAnimationHookPath,
  nativeInputFingerprint,
  recordJsBundle,
  run,
  setGentleMode,
  visualDirectory,
} from "./visual-runner.mjs";


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
export const metroConfigPath = path.join(mobileRoot, "visual/metro.config.js");
const expoRouterEntryPath = path.resolve(
  mobileRoot,
  "../node_modules/expo-router/entry.js",
);

function usage() {
  console.log(`Usage:
  npm run visual:ios:capture -- [options]

Options:
  --device <name-or-udid>  Simulator to use
  --show-simulator         Open Simulator.app while capturing
  --skip-build             Skip even the fast JavaScript rebundle
  --clean-native           Regenerate the cached native iOS project
  --gentle                 One simulator shard at utility QoS: slower, but the
                           machine stays responsive
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
    if (argument === "--device") {
      const value = argumentsCopy[index + 1];
      if (!value) throw new Error(`${argument} requires a value.`);
      index += 1;
      options.device = value;
      continue;
    }
    throw new Error(`Unknown argument: ${argument}`);
  }

  if (command !== "capture") {
    throw new Error(`Unknown command: ${command}`);
  }
  if (options.skipBuild && options.cleanNative) {
    throw new Error("--skip-build and --clean-native cannot be used together.");
  }
  return options;
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
        "CAPTURE_URL=",
        "-e",
        `CAPTURE_URL_1=${bridge.urls[0]}`,
        "-e",
        `CAPTURE_URL_2=${bridge.urls[1]}`,
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


async function prepareCaptureSession(options) {
  await recoverGeneratedIosSwap();
  await assertHarnessBoundary();
  const registry = await loadRegistry("mobile");
  const manifest = { ...registry, scenarios: scenariosForPlatform(registry, "ios") };
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
  const registry = await loadRegistry("mobile");
  const manifest = { ...registry, scenarios: scenariosForPlatform(registry, "ios") };
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
    // Xcode's module cache pins absolute paths, so a moved checkout must drop it too.
    await rm(derivedDataDirectory, { recursive: true, force: true });
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
    publishRunStatus("capturing", { message, startedAt, runner: "ios" });
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
      message: `Captured ${result.produced.size} iOS screenshots`,
      detail: result.warning,
      runner: "ios",
    });
  } catch (error) {
    await publishRunStatus("error", {
      message: "iOS capture failed",
      detail: error instanceof Error ? error.message : String(error),
      runner: "ios",
    });
    throw error;
  }
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
      const temporary = path.join(
        os.tmpdir(),
        `vesta-visual-${process.pid}-${screenshot}`,
      );
      await run(
        "xcrun",
        ["simctl", "io", simulator.udid, "screenshot", "--type=png", temporary],
        { capture: true, quiet: true },
      );
      await putShot("ios", screenshot, temporary);
      await rm(temporary, { force: true });
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

function reportShotDrift(seen, manifest) {
  const warning = shotDriftWarning(seen, manifest.scenarios);
  if (warning) console.warn(`\nShot registry drift: ${warning}`);
  console.log(`\nCaptured ${seen.size} iOS screenshots into the visual store.`);
  return warning;
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  setGentleMode(options.gentle);
  await capture(options);
}

const invokedAsScript =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedAsScript) {
  main().catch((error) => {
    console.error(`\niOS visual capture failed: ${error.message}`);
    process.exitCode = 1;
  });
}