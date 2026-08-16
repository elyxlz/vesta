#!/usr/bin/env node
// Android visual catalog runner: captures the same manifest as the iOS runner
// on one dedicated Android emulator and publishes the same gallery format.

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import {
  copyFile,
  mkdir,
  readdir,
  readFile,
  rename,
  rm,
  stat,
} from "node:fs/promises";
import { fileURLToPath } from "node:url";
import os from "node:os";
import path from "node:path";

import {
  assertHarnessBoundary,
  atomicWriteFile,
  exists,
  filesBelow,
  galleryHtml,
  gitMetadata,
  loadManifest,
  nativeInputFingerprint,
  pngSize,
  run,
  scenarioOnPlatform,
  serveCatalog,
} from "./visual-catalog.mjs";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const mobileRoot = path.resolve(scriptDirectory, "..");
const androidVisualDirectory = path.join(mobileRoot, ".visual/android");
const screenshotsDirectory = path.join(androidVisualDirectory, "screenshots");
const captureScreenshotsDirectory = path.join(
  androidVisualDirectory,
  "capture/screenshots",
);
const maestroDirectory = path.join(androidVisualDirectory, "maestro");
const apkPath = path.join(androidVisualDirectory, "apk/app-release.apk");
const nativeAndroidDirectory = path.join(mobileRoot, ".visual/native/android");
const androidFingerprintPath = path.join(
  mobileRoot,
  ".visual/native/android-fingerprint.txt",
);
const nativeTransactionDirectory = path.join(
  mobileRoot,
  ".expo/visual-android-transaction",
);
const nativeTransactionStatePath = path.join(
  nativeTransactionDirectory,
  "state.json",
);
const metroConfigPath = path.join(mobileRoot, "visual/metro.config.js");
const DEFAULT_AVD_NAME = "vesta-visual";
const DEFAULT_GALLERY_PORT = 4174;
const ANDROID_BUILD_ABI = "arm64-v8a";
const EMULATOR_BOOT_TIMEOUT_MS = 240_000;
const EMULATOR_BOOT_POLL_MS = 2_000;
const STATUS_BAR_CLOCK = "0941";
const KEPT_PREVIOUS_RELEASES = 2;

function usage() {
  console.log(`Usage:
  npm run visual:android -- [options]
  npm run visual:android:serve -- [options]

Commands:
  capture       Build, capture, generate, and serve the catalog (default)
  serve         Serve the most recently generated Android catalog

Options:
  --avd <name>        Emulator AVD to boot or reuse (default: ${DEFAULT_AVD_NAME})
  --device <serial>   Use an already-connected adb device instead
  --show-emulator     Boot the emulator with a visible window
  --skip-build        Reuse the installed visual app without building
  --clean-native      Regenerate the cached native Android project
  --no-serve          Capture without starting the gallery server
  --no-open           Do not open the gallery in a browser
  --port <number>     Gallery port (default: ${DEFAULT_GALLERY_PORT})
  --help              Show this help
`);
}

export function parseArguments(values) {
  const argumentsCopy = [...values];
  const command =
    argumentsCopy[0] && !argumentsCopy[0].startsWith("-")
      ? argumentsCopy.shift()
      : "capture";
  const options = {
    command,
    avd: DEFAULT_AVD_NAME,
    device: "",
    showEmulator: false,
    skipBuild: false,
    cleanNative: false,
    serve: true,
    open: true,
    port: DEFAULT_GALLERY_PORT,
  };

  for (let index = 0; index < argumentsCopy.length; index += 1) {
    const argument = argumentsCopy[index];
    if (argument === "--help") {
      usage();
      process.exit(0);
    }
    if (argument === "--show-emulator") {
      options.showEmulator = true;
      continue;
    }
    if (argument === "--skip-build") {
      options.skipBuild = true;
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
    if (["--avd", "--device", "--port"].includes(argument)) {
      const value = argumentsCopy[index + 1];
      if (!value) throw new Error(`${argument} requires a value.`);
      index += 1;
      if (argument === "--avd") options.avd = value;
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

  if (!["capture", "serve"].includes(command)) {
    throw new Error(`Unknown command: ${command}`);
  }
  if (options.skipBuild && options.cleanNative) {
    throw new Error("--skip-build and --clean-native cannot be used together.");
  }
  return options;
}

function androidSdkRoot() {
  const candidates = [
    process.env.ANDROID_HOME,
    process.env.ANDROID_SDK_ROOT,
    path.join(os.homedir(), "Library/Android/sdk"),
    path.join(os.homedir(), "Android/Sdk"),
  ].filter(Boolean);
  const sdk = candidates.find((candidate) =>
    existsSync(path.join(candidate, "platform-tools/adb")),
  );
  if (!sdk) {
    throw new Error(
      "Could not find the Android SDK. Set ANDROID_HOME to an SDK with platform-tools.",
    );
  }
  return sdk;
}

async function requireCaptureTools() {
  const sdk = androidSdkRoot();
  const adb = path.join(sdk, "platform-tools/adb");
  const emulator = path.join(sdk, "emulator/emulator");
  const maestroCandidates = [
    path.join(os.homedir(), ".maestro/bin/maestro"),
    "/opt/homebrew/bin/maestro",
    "/usr/local/bin/maestro",
  ];
  const maestro = maestroCandidates.find((candidate) => existsSync(candidate));
  if (!maestro) {
    throw new Error(
      "Maestro CLI is required. Install it with:\n" +
        "  brew tap mobile-dev-inc/tap\n" +
        "  brew install mobile-dev-inc/tap/maestro",
    );
  }
  const javaPrefixes = [
    process.env.JAVA_HOME,
    "/opt/homebrew/opt/openjdk@17",
    "/opt/homebrew/opt/openjdk",
    "/usr/local/opt/openjdk",
  ].filter(Boolean);
  const javaPrefix = javaPrefixes.find((candidate) =>
    existsSync(path.join(candidate, "bin/java")),
  );
  if (!javaPrefix) {
    throw new Error(
      "A Java 17+ runtime is required for Gradle and Maestro. Set JAVA_HOME.",
    );
  }
  const environment = {
    ANDROID_HOME: sdk,
    JAVA_HOME: javaPrefix,
    PATH: `${path.join(javaPrefix, "bin")}:${path.join(sdk, "platform-tools")}:${
      process.env.PATH ?? ""
    }`,
    MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED: "true",
    MAESTRO_CLI_NO_ANALYTICS: "1",
    MAESTRO_DRIVER_STARTUP_TIMEOUT:
      process.env.MAESTRO_DRIVER_STARTUP_TIMEOUT ?? "300000",
  };
  return { adb, emulator, maestro, environment };
}

async function adb(tools, serial, argumentsList, options = {}) {
  return run(tools.adb, ["-s", serial, ...argumentsList], {
    capture: true,
    ...options,
  });
}

async function connectedEmulators(tools) {
  const result = await run(tools.adb, ["devices"], { capture: true });
  return result.stdout
    .split("\n")
    .filter((line) => line.trim().endsWith("device"))
    .map((line) => line.split("\t")[0])
    .filter((serial) => serial.startsWith("emulator-"));
}

async function avdNameOf(tools, serial) {
  const result = await adb(tools, serial, ["emu", "avd", "name"], {
    allowFailure: true,
  });
  return result.stdout.split("\n")[0]?.trim() ?? "";
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function waitForBoot(tools, serial) {
  const deadline = Date.now() + EMULATOR_BOOT_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const result = await adb(
      tools,
      serial,
      ["shell", "getprop", "sys.boot_completed"],
      { allowFailure: true },
    );
    if (result.stdout.trim() === "1") return;
    await delay(EMULATOR_BOOT_POLL_MS);
  }
  throw new Error(`Emulator ${serial} did not finish booting in time.`);
}

async function bootEmulator(tools, options) {
  const avds = (
    await run(tools.emulator, ["-list-avds"], { capture: true })
  ).stdout
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (!avds.includes(options.avd)) {
    throw new Error(
      `AVD "${options.avd}" does not exist. Create it in Android Studio or with avdmanager.`,
    );
  }
  const before = new Set(await connectedEmulators(tools));
  const emulatorArguments = [
    "-avd",
    options.avd,
    "-no-audio",
    "-no-boot-anim",
    "-gpu",
    "swiftshader_indirect",
    ...(options.showEmulator ? [] : ["-no-window"]),
  ];
  console.log(`\n› ${tools.emulator} ${emulatorArguments.join(" ")}`);
  const child = spawn(tools.emulator, emulatorArguments, {
    detached: true,
    stdio: "ignore",
  });
  child.unref();

  const deadline = Date.now() + EMULATOR_BOOT_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const serial = (await connectedEmulators(tools)).find(
      (candidate) => !before.has(candidate),
    );
    if (serial) {
      await waitForBoot(tools, serial);
      return serial;
    }
    await delay(EMULATOR_BOOT_POLL_MS);
  }
  throw new Error(`AVD "${options.avd}" did not appear on adb in time.`);
}

async function prepareEmulator(tools, options) {
  const connected = await connectedEmulators(tools);
  if (options.device) {
    if (!connected.includes(options.device)) {
      throw new Error(`Device ${options.device} is not connected.`);
    }
    await waitForBoot(tools, options.device);
    return options.device;
  }
  for (const serial of connected) {
    if ((await avdNameOf(tools, serial)) === options.avd) {
      await waitForBoot(tools, serial);
      return serial;
    }
  }
  return bootEmulator(tools, options);
}

async function emulatorRuntime(tools, serial) {
  const release = (
    await adb(tools, serial, ["shell", "getprop", "ro.build.version.release"])
  ).stdout.trim();
  const sdk = (
    await adb(tools, serial, ["shell", "getprop", "ro.build.version.sdk"])
  ).stdout.trim();
  return `Android ${release} (API ${sdk})`;
}

async function demoModeCommand(tools, serial, command, extras = []) {
  await adb(
    tools,
    serial,
    [
      "shell",
      "am",
      "broadcast",
      "-a",
      "com.android.systemui.demo",
      "-e",
      "command",
      command,
      ...extras,
    ],
    { allowFailure: true },
  );
}

async function normalizeEmulator(tools, serial) {
  const settings = [
    ["global", "window_animation_scale", "0"],
    ["global", "transition_animation_scale", "0"],
    ["global", "animator_duration_scale", "0"],
    ["system", "font_scale", "1.0"],
    ["global", "sysui_demo_allowed", "1"],
  ];
  for (const [namespace, key, value] of settings) {
    await adb(tools, serial, ["shell", "settings", "put", namespace, key, value]);
  }
  await adb(tools, serial, ["shell", "cmd", "uimode", "night", "no"], {
    allowFailure: true,
  });
  await demoModeCommand(tools, serial, "enter");
  await demoModeCommand(tools, serial, "clock", ["-e", "hhmm", STATUS_BAR_CLOCK]);
  await demoModeCommand(tools, serial, "battery", [
    "-e",
    "level",
    "100",
    "-e",
    "plugged",
    "false",
  ]);
  await demoModeCommand(tools, serial, "network", [
    "-e",
    "wifi",
    "show",
    "-e",
    "level",
    "4",
  ]);
  await demoModeCommand(tools, serial, "network", [
    "-e",
    "mobile",
    "show",
    "-e",
    "datatype",
    "none",
    "-e",
    "level",
    "4",
  ]);
  await demoModeCommand(tools, serial, "notifications", [
    "-e",
    "visible",
    "false",
  ]);
}

async function restoreEmulator(tools, serial) {
  await demoModeCommand(tools, serial, "exit");
}

async function isVisualAndroidProject(androidDirectory, appId) {
  const gradleFile = path.join(androidDirectory, "app/build.gradle");
  if (!(await exists(gradleFile))) return false;
  return (await readFile(gradleFile, "utf8")).includes(
    `applicationId '${appId}'`,
  );
}

async function moveVisualAndroidToCache(androidDirectory) {
  await mkdir(path.dirname(nativeAndroidDirectory), { recursive: true });
  await rm(nativeAndroidDirectory, { recursive: true, force: true });
  await rename(androidDirectory, nativeAndroidDirectory);
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

async function recoverGeneratedAndroidSwap(appId) {
  const androidDirectory = path.join(mobileRoot, "android");
  const savedAndroidDirectory = path.join(
    nativeTransactionDirectory,
    "original-android",
  );

  if (await exists(nativeTransactionDirectory)) {
    let state;
    try {
      state = JSON.parse(await readFile(nativeTransactionStatePath, "utf8"));
    } catch {
      state = null;
    }
    if (state?.pid !== process.pid && processIsRunning(Number(state?.pid))) {
      throw new Error(
        `Another visual native build is active (PID ${state.pid}).`,
      );
    }
    if (await exists(savedAndroidDirectory)) {
      if (await exists(androidDirectory)) {
        await moveVisualAndroidToCache(androidDirectory);
      }
      await rename(savedAndroidDirectory, androidDirectory);
      console.log(
        "\nRecovered the production android/ directory from an interrupted visual build.",
      );
    } else if (state?.hadAndroid === false && (await exists(androidDirectory))) {
      await moveVisualAndroidToCache(androidDirectory);
    }
    await rm(nativeTransactionDirectory, { recursive: true, force: true });
  }

  // A visual project generated outside this runner (or interrupted before the
  // cache move) sits at android/ with the visual application id. Adopt it as
  // the cache so it is never mistaken for a production prebuild.
  if (
    !(await exists(nativeAndroidDirectory)) &&
    (await isVisualAndroidProject(androidDirectory, appId))
  ) {
    await moveVisualAndroidToCache(androidDirectory);
    await atomicWriteFile(
      androidFingerprintPath,
      `${await nativeInputFingerprint()}\n`,
    );
    console.log("\nAdopted an existing visual android/ project as the cache.");
  }
}

async function withGeneratedAndroid(appId, callback) {
  await recoverGeneratedAndroidSwap(appId);
  await mkdir(path.join(mobileRoot, ".expo"), { recursive: true });
  await mkdir(path.dirname(nativeAndroidDirectory), { recursive: true });
  await mkdir(nativeTransactionDirectory, { recursive: false });
  const androidDirectory = path.join(mobileRoot, "android");
  const savedAndroidDirectory = path.join(
    nativeTransactionDirectory,
    "original-android",
  );
  const hadAndroid = await exists(androidDirectory);
  const hadCachedAndroid = await exists(nativeAndroidDirectory);
  await atomicWriteFile(
    nativeTransactionStatePath,
    `${JSON.stringify({ pid: process.pid, hadAndroid, hadCachedAndroid })}\n`,
  );

  let reusable = false;
  let result;
  try {
    if (hadAndroid) await rename(androidDirectory, savedAndroidDirectory);
    if (hadCachedAndroid) await rename(nativeAndroidDirectory, androidDirectory);
    result = await callback(androidDirectory, hadCachedAndroid);
    reusable = true;
  } finally {
    let cleanupError;
    try {
      if (await exists(androidDirectory)) {
        if (reusable) await moveVisualAndroidToCache(androidDirectory);
        else await rm(androidDirectory, { recursive: true, force: true });
      }
      if (await exists(savedAndroidDirectory)) {
        await rename(savedAndroidDirectory, androidDirectory);
      }
      await rm(nativeTransactionDirectory, { recursive: true, force: true });
    } catch (error) {
      cleanupError = error;
    }
    if (cleanupError) throw cleanupError;
  }
  return result;
}

async function buildAndInstall(tools, serial, appId, options) {
  if (options.cleanNative) {
    await rm(nativeAndroidDirectory, { recursive: true, force: true });
    await rm(androidFingerprintPath, { force: true });
  }
  const currentNativeFingerprint = await nativeInputFingerprint();
  const cachedNativeFingerprint = (await exists(androidFingerprintPath))
    ? (await readFile(androidFingerprintPath, "utf8")).trim()
    : "";
  if (
    currentNativeFingerprint !== cachedNativeFingerprint &&
    (await exists(nativeAndroidDirectory))
  ) {
    console.log("\nNative inputs changed; regenerating the visual Android cache.");
    await rm(nativeAndroidDirectory, { recursive: true, force: true });
  }
  const visualEnvironment = {
    CI: "1",
    EXPO_OVERRIDE_METRO_CONFIG: metroConfigPath,
    VESTA_APP_VARIANT: "development",
    VESTA_APP_BUNDLE_ID: appId,
  };

  await withGeneratedAndroid(appId, async (androidDirectory, hadCachedAndroid) => {
    if (!hadCachedAndroid) {
      await run("npx", ["expo", "prebuild", "--clean", "--platform", "android"], {
        env: { ...tools.environment, ...visualEnvironment },
      });
    }
    await run(
      path.join(androidDirectory, "gradlew"),
      [
        ":app:assembleRelease",
        `-PreactNativeArchitectures=${ANDROID_BUILD_ABI}`,
        "--console=plain",
      ],
      { cwd: androidDirectory, env: { ...tools.environment, ...visualEnvironment } },
    );
    const builtApk = path.join(
      androidDirectory,
      "app/build/outputs/apk/release/app-release.apk",
    );
    const metadataPath = path.join(
      androidDirectory,
      "app/build/outputs/apk/release/output-metadata.json",
    );
    const metadata = JSON.parse(await readFile(metadataPath, "utf8"));
    if (metadata.applicationId !== appId) {
      throw new Error(
        `The built APK carries ${metadata.applicationId}, expected ${appId}.`,
      );
    }
    await mkdir(path.dirname(apkPath), { recursive: true });
    await copyFile(builtApk, apkPath);
  });
  await atomicWriteFile(androidFingerprintPath, `${currentNativeFingerprint}\n`);
  await adb(tools, serial, ["install", "-r", apkPath], { capture: false });
}

async function requireInstalledApp(tools, serial, appId) {
  const result = await adb(tools, serial, [
    "shell",
    "pm",
    "list",
    "packages",
    appId,
  ]);
  if (!result.stdout.includes(`package:${appId}`)) {
    throw new Error(
      `${appId} is not installed on ${serial}. Run without --skip-build first.`,
    );
  }
}

async function runMaestro(manifest, tools, serial) {
  await rm(captureScreenshotsDirectory, { recursive: true, force: true });
  await rm(maestroDirectory, { recursive: true, force: true });
  await mkdir(captureScreenshotsDirectory, { recursive: true });
  await mkdir(maestroDirectory, { recursive: true });

  const flowPaths = manifest.flows.map((flow) => path.resolve(mobileRoot, flow));
  await run(
    tools.maestro,
    [
      `--device=${serial}`,
      "test",
      ...flowPaths,
      "-e",
      `APP_ID=${manifest.appId}`,
      `--test-output-dir=${maestroDirectory}`,
      "--format=HTML",
      `--output=${path.join(maestroDirectory, "report.html")}`,
      "--test-suite-name=Vesta visual catalog (Android)",
    ],
    { cwd: captureScreenshotsDirectory, env: tools.environment },
  );

  // Maestro's suite mode writes each takeScreenshot artifact into its flow's
  // takeScreenshot/ directory under the test output; stage them by name.
  const expected = new Set(
    manifest.scenarios.map((scenario) => scenario.screenshot),
  );
  const produced = new Map();
  for (const file of await filesBelow(maestroDirectory)) {
    if (!file.endsWith(".png")) continue;
    if (path.basename(path.dirname(file)) !== "takeScreenshot") continue;
    const name = path.basename(file);
    if (produced.has(name)) {
      throw new Error(`Duplicate Android screenshot across flows: ${name}`);
    }
    produced.set(name, file);
  }
  const unexpected = [...produced.keys()].filter((name) => !expected.has(name));
  if (unexpected.length > 0) {
    throw new Error(
      `Unexpected Android screenshots (check flow platform conditions): ${unexpected.join(", ")}`,
    );
  }
  for (const [name, file] of produced) {
    await copyFile(file, path.join(captureScreenshotsDirectory, name));
  }
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
      .slice(0, KEPT_PREVIOUS_RELEASES)
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

export function catalogScenarios(allScenarios, release, sizes) {
  return allScenarios.map((scenario) =>
    scenarioOnPlatform(scenario, "android")
      ? {
          ...scenario,
          captured: true,
          image: `screenshots/${release}/${scenario.screenshot}`,
          size: sizes.get(scenario.screenshot) ?? null,
        }
      : {
          ...scenario,
          captured: false,
          image: "",
          size: null,
          missingLabel: "iOS only",
        },
  );
}

async function publishGallery(manifest, device, reportAvailable) {
  await mkdir(screenshotsDirectory, { recursive: true });
  const release = `${Date.now()}-${process.pid}`;
  const releaseDirectory = path.join(screenshotsDirectory, release);
  await mkdir(releaseDirectory, { recursive: true });

  const sizes = new Map();
  const invalid = [];
  for (const scenario of manifest.scenarios) {
    const source = path.join(captureScreenshotsDirectory, scenario.screenshot);
    if (!(await exists(source))) {
      invalid.push(scenario.screenshot);
      continue;
    }
    const size = await pngSize(source);
    if (!size) {
      invalid.push(scenario.screenshot);
      continue;
    }
    await copyFile(source, path.join(releaseDirectory, scenario.screenshot));
    sizes.set(scenario.screenshot, size);
  }
  if (invalid.length > 0) {
    throw new Error(`Missing or invalid screenshots: ${invalid.join(", ")}`);
  }

  const catalog = {
    generatedAt: new Date().toISOString(),
    appId: manifest.appId,
    platform: "android",
    mode: "capture",
    reportAvailable,
    device,
    git: await gitMetadata(),
    scenarios: catalogScenarios(manifest.allScenarios, release, sizes),
  };
  await atomicWriteFile(
    path.join(androidVisualDirectory, "index.html"),
    galleryHtml(catalog),
  );
  await atomicWriteFile(
    path.join(androidVisualDirectory, "catalog.json"),
    `${JSON.stringify(catalog, null, 2)}\n`,
  );
  try {
    await cleanupScreenshotReleases(release);
  } catch (error) {
    console.warn(`Could not prune old screenshot releases: ${error.message}`);
  }
  return catalog;
}

async function capture(options) {
  await assertHarnessBoundary();
  const manifest = await loadManifest("android");
  const tools = await requireCaptureTools();
  await mkdir(androidVisualDirectory, { recursive: true });
  const serial = await prepareEmulator(tools, options);
  const avdName = options.device
    ? await avdNameOf(tools, serial)
    : options.avd;
  console.log(`\nUsing Android emulator ${serial} (${avdName}).`);
  await normalizeEmulator(tools, serial);
  try {
    if (options.skipBuild) {
      await requireInstalledApp(tools, serial, manifest.appId);
    } else {
      await buildAndInstall(tools, serial, manifest.appId, options);
    }
    await runMaestro(manifest, tools, serial);
    const catalog = await publishGallery(
      manifest,
      {
        name: `${avdName || serial} (Android emulator)`,
        udid: serial,
        runtime: await emulatorRuntime(tools, serial),
      },
      await exists(path.join(maestroDirectory, "report.html")),
    );
    const captured = catalog.scenarios.filter(
      (scenario) => scenario.captured,
    ).length;
    console.log(
      `\nCaptured ${captured} Android screenshots (${
        catalog.scenarios.length - captured
      } scenarios are iOS only).`,
    );
  } finally {
    await restoreEmulator(tools, serial);
  }

  if (options.serve) {
    await serveCatalog(options.port, options.open, androidVisualDirectory);
  }
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  if (options.command === "serve") {
    await serveCatalog(options.port, options.open, androidVisualDirectory);
    return;
  }
  await capture(options);
}

const isDirectRun =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isDirectRun) {
  main().catch((error) => {
    console.error(`\n${error.message}`);
    process.exit(1);
  });
}
