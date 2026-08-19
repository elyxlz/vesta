#!/usr/bin/env node
// Android visual catalog runner: captures the same scenario registry as the
// iOS runner on one dedicated Android emulator and replaces the Android shot
// files the shared gallery composes from.

import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import { existsSync } from "node:fs";
import { copyFile, mkdir, readFile, rename, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import os from "node:os";
import path from "node:path";

import { loadRegistry, scenariosForPlatform } from "@vesta/visual/registry";
import { publishRunStatus } from "@vesta/visual/run-status";
import { captureAllRequested } from "@vesta/visual/fingerprint";
import { putShot, shotDriftWarning } from "@vesta/visual/store";
import {
  assertHarnessBoundary,
  atomicWriteFile,
  captureBothThemes,
  exists,
  flowFailureError,
  gentleSpawnPlan,
  jsBundleCurrent,
  metroConfigPath,
  nativeInputFingerprint,
  planFlows,
  printPlan,
  recordJsBundle,
  run,
  setGentleMode,
  startScreenshotBridge,
  visualDirectory,
} from "./visual-runner.mjs";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const mobileRoot = path.resolve(scriptDirectory, "..");
const androidVisualDirectory = path.join(visualDirectory, "android");
// One variant per run: the same build and flows on a different emulator persona. The galaxy
// variant runs classic 3-button navigation, so every screen is exercised with a visible bottom
// navigation bar and its status bar insets.
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
function androidMaestroDirectoryOf(variant) {
  const workDirectory =
    variant === "android"
      ? androidVisualDirectory
      : path.join(visualDirectory, variant);
  return path.join(workDirectory, "maestro");
}
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
const DEFAULT_VARIANT = "android";
const SCREENCAP_MAX_BYTES = 64 * 1024 * 1024;
const execFileAsync = promisify(execFile);
const ANDROID_BUILD_ABI = "arm64-v8a";
const EMULATOR_BOOT_TIMEOUT_MS = 240_000;
const EMULATOR_BOOT_POLL_MS = 2_000;
const STATUS_BAR_CLOCK = "0941";
const DISPLAY_CUTOUT_OVERLAY =
  "com.android.internal.display.cutout.emulation.tall";

function usage() {
  console.log(`Usage:
  npm run visual:android:capture -- [options]

Commands:
  capture             Take the shots whose inputs changed (default)
  plan                Print which flows a capture would run, as JSON

Options:
  --all               Retake every shot, changed or not
  --variant <key>     Android variant to capture: ${Object.keys(androidVariants).join(", ")}
                      (default: ${DEFAULT_VARIANT}; the galaxy variant runs 3-button navigation)
  --avd <name>        Emulator AVD to boot or reuse (default: the variant's AVD)
  --device <serial>   Use an already-connected adb device instead
  --show-emulator     Boot the emulator with a visible window
  --skip-build        Reuse the installed visual app without building
  --clean-native      Regenerate the cached native Android project
  --gentle            Run build, emulator, and Maestro at utility QoS:
                      slower, but the machine stays responsive
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
    variant: DEFAULT_VARIANT,
    avd: "",
    device: "",
    showEmulator: false,
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
    if (argument === "--gentle") {
      options.gentle = true;
      continue;
    }
    if (argument === "--all") {
      options.all = true;
      continue;
    }
    if (["--avd", "--device", "--variant"].includes(argument)) {
      const value = argumentsCopy[index + 1];
      if (!value) throw new Error(`${argument} requires a value.`);
      index += 1;
      if (argument === "--avd") options.avd = value;
      if (argument === "--variant") options.variant = value;
      if (argument === "--device") options.device = value;
      continue;
    }
    throw new Error(`Unknown argument: ${argument}`);
  }

  if (command !== "capture" && command !== "plan") {
    throw new Error(`Unknown command: ${command}`);
  }
  if (options.skipBuild && options.cleanNative) {
    throw new Error("--skip-build and --clean-native cannot be used together.");
  }
  if (!(options.variant in androidVariants)) {
    throw new Error(
      `Unknown Android variant: ${options.variant}. Known: ${Object.keys(
        androidVariants,
      ).join(", ")}`,
    );
  }
  if (!options.avd) options.avd = androidVariants[options.variant].avd;
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
  const plan = gentleSpawnPlan(
    tools.emulator,
    emulatorArguments,
    options.gentle,
    process.platform,
  );
  const child = spawn(plan.command, plan.argumentsList, {
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

async function normalizeEmulator(tools, serial, navOverlay) {
  const settings = [
    ["global", "window_animation_scale", "0"],
    ["global", "transition_animation_scale", "0"],
    ["global", "animator_duration_scale", "0"],
    ["system", "font_scale", "1.0"],
    ["global", "sysui_demo_allowed", "1"],
  ];
  for (const [namespace, key, value] of settings) {
    await adb(tools, serial, [
      "shell",
      "settings",
      "put",
      namespace,
      key,
      value,
    ]);
  }
  await adb(tools, serial, ["shell", "cmd", "uimode", "night", "no"], {
    allowFailure: true,
  });
  // The variant decides the system navigation persona: gesture pill or 3-button bar.
  await adb(
    tools,
    serial,
    ["shell", "cmd", "overlay", "enable-exclusive", navOverlay],
    { allowFailure: true },
  );
  // A centred display cutout, so the status bar and content sit below the camera
  // as on the device; the stock image has no cutout and would hug the corners.
  await adb(
    tools,
    serial,
    [
      "shell",
      "cmd",
      "overlay",
      "enable-exclusive",
      "--category",
      DISPLAY_CUTOUT_OVERLAY,
    ],
    { allowFailure: true },
  );
  await demoModeCommand(tools, serial, "enter");
  await demoModeCommand(tools, serial, "clock", [
    "-e",
    "hhmm",
    STATUS_BAR_CLOCK,
  ]);
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
  await adb(
    tools,
    serial,
    ["shell", "cmd", "overlay", "disable", DISPLAY_CUTOUT_OVERLAY],
    {
      allowFailure: true,
    },
  );
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
    } else if (
      state?.hadAndroid === false &&
      (await exists(androidDirectory))
    ) {
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
  let failure;
  try {
    if (hadAndroid) await rename(androidDirectory, savedAndroidDirectory);
    if (hadCachedAndroid)
      await rename(nativeAndroidDirectory, androidDirectory);
    result = await callback(androidDirectory, hadCachedAndroid);
    reusable = true;
  } catch (error) {
    failure = error;
  }
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
  if (cleanupError && failure) {
    throw new AggregateError(
      [failure, cleanupError],
      "The visual native build failed and its cleanup failed too.",
    );
  }
  if (cleanupError) throw cleanupError;
  if (failure) throw failure;
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
    console.log(
      "\nNative inputs changed; regenerating the visual Android cache.",
    );
    await rm(nativeAndroidDirectory, { recursive: true, force: true });
  }
  const visualEnvironment = {
    CI: "1",
    EXPO_OVERRIDE_METRO_CONFIG: metroConfigPath,
    VESTA_APP_VARIANT: "development",
    VESTA_APP_BUNDLE_ID: appId,
  };

  await withGeneratedAndroid(
    appId,
    async (androidDirectory, hadCachedAndroid) => {
      if (!hadCachedAndroid) {
        await run(
          "npx",
          ["expo", "prebuild", "--clean", "--platform", "android"],
          {
            env: { ...tools.environment, ...visualEnvironment },
          },
        );
      }
      await run(
        path.join(androidDirectory, "gradlew"),
        [
          ":app:assembleRelease",
          `-PreactNativeArchitectures=${ANDROID_BUILD_ABI}`,
          "--console=plain",
        ],
        {
          cwd: androidDirectory,
          env: { ...tools.environment, ...visualEnvironment },
        },
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
    },
  );
  await atomicWriteFile(
    androidFingerprintPath,
    `${currentNativeFingerprint}\n`,
  );
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

// adb streams the framebuffer PNG on stdout, so the grab is a binary exec.
async function grabEmulatorScreen(tools, serial) {
  const { stdout } = await execFileAsync(
    tools.adb,
    ["-s", serial, "exec-out", "screencap", "-p"],
    { encoding: "buffer", maxBuffer: SCREENCAP_MAX_BYTES },
  );
  return stdout;
}

// The shared bridge with the Android handlers: a screencap grab in both night
// modes. The keyboard renders inside the framebuffer, so there is no action.
function startAndroidBridge(tools, serial, variant, records) {
  return startScreenshotBridge([serial], {
    capture: (target, screenshot) =>
      captureBothThemes({
        platform: variant,
        name: screenshot,
        record: records.get(screenshot),
        grab: () => grabEmulatorScreen(tools, target),
        setDark: (dark) =>
          adb(
            tools,
            target,
            ["shell", "cmd", "uimode", "night", dark ? "yes" : "no"],
            {
              quiet: true,
            },
          ),
        store: putShot,
      }),
  });
}

async function runMaestro(manifest, tools, serial, variant, records) {
  const maestroDirectory = androidMaestroDirectoryOf(variant);
  await rm(maestroDirectory, { recursive: true, force: true });
  await mkdir(maestroDirectory, { recursive: true });

  const flowPaths = manifest.flows.map((flow) =>
    path.resolve(mobileRoot, flow),
  );
  const bridge = await startAndroidBridge(tools, serial, variant, records);
  const cycle = await bridge.beginCycle(manifest);
  try {
    await run(
      tools.maestro,
      [
        `--device=${serial}`,
        "test",
        ...flowPaths,
        "-e",
        `APP_ID=${manifest.appId}`,
        "-e",
        `CAPTURE_URL=${bridge.urls[0]}`,
        `--test-output-dir=${maestroDirectory}`,
        "--format=HTML",
        `--output=${path.join(maestroDirectory, "report.html")}`,
        "--test-suite-name=Vesta visual catalog (Android)",
      ],
      { cwd: maestroDirectory, env: tools.environment, tee: true },
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

// The files that shape how a shot is taken, on top of the app sources a flow
// reaches: a change here retakes every shot.
const androidMechanics = [
  path.join(mobileRoot, "maestro/visual/capture-screenshot.js"),
  path.join(mobileRoot, "scripts/visual-runner.mjs"),
  path.join(mobileRoot, "scripts/visual-sources.mjs"),
  path.join(mobileRoot, "scripts/visual-android.mjs"),
];

async function capture(options) {
  const startedAt = new Date().toISOString();
  const variant = options.variant;
  const phase = (message) =>
    publishRunStatus("capturing", { message, startedAt, runner: variant });
  await assertHarnessBoundary();
  const registry = await loadRegistry("mobile");
  const manifest = {
    ...registry,
    scenarios: scenariosForPlatform(registry, variant),
  };
  const tools = await requireCaptureTools();
  await mkdir(androidVisualDirectory, { recursive: true });
  // Everything after the first "capturing" phase publishes its outcome, so an
  // emulator that fails to boot never leaves the gallery on a phantom scan.
  let serial = "";
  try {
    await phase(`Preparing the ${androidVariants[variant].label} emulator`);
    serial = await prepareEmulator(tools, options);
    const avdName = options.device
      ? await avdNameOf(tools, serial)
      : options.avd;
    console.log(`\nUsing Android emulator ${serial} (${avdName}).`);
    await normalizeEmulator(tools, serial, androidVariants[variant].navOverlay);
    await phase(
      options.skipBuild
        ? "Checking the installed Android visual app"
        : "Building and installing the Android visual app",
    );
    if (options.skipBuild) {
      await requireInstalledApp(tools, serial, manifest.appId);
    } else if (
      !options.cleanNative &&
      (await jsBundleCurrent(variant)) &&
      (await requireInstalledApp(tools, serial, manifest.appId)
        .then(() => true)
        .catch(() => false))
    ) {
      console.log("\nJS inputs unchanged; reusing the installed app.");
    } else {
      await buildAndInstall(tools, serial, manifest.appId, options);
      await recordJsBundle(variant);
    }
    await phase("Planning the Android flows");
    const plan = await planFlows(manifest, {
      platform: variant,
      metroPlatform: "android",
      mechanics: androidMechanics,
      extras: [await nativeInputFingerprint()],
      captureAll: options.all || captureAllRequested(),
    });
    if (plan.skipped.length > 0) {
      console.log(
        `\nSkipping ${plan.skipped.length} unchanged flow(s): ${plan.skipped
          .map((flow) => path.basename(flow))
          .join(", ")}`,
      );
    }
    const planned = {
      ...manifest,
      flows: plan.flows,
      scenarios: plan.scenarios,
    };
    await phase(
      `Running ${planned.flows.length} flows on the Android emulator`,
    );
    const produced =
      planned.flows.length === 0
        ? new Set()
        : await runMaestro(planned, tools, serial, variant, plan.records);
    const warning = shotDriftWarning(produced, planned.scenarios);
    if (warning) console.warn(`\nShot registry drift: ${warning}`);
    console.log(
      `\nCaptured ${produced.size} ${androidVariants[variant].label} screenshots into the visual store.`,
    );
    await publishRunStatus("ready", {
      message: `Captured ${produced.size} ${androidVariants[variant].label} screenshots`,
      detail: warning,
      runner: variant,
    });
  } catch (error) {
    await publishRunStatus("error", {
      message: `${androidVariants[variant].label} capture failed`,
      detail: error instanceof Error ? error.message : String(error),
      runner: variant,
    });
    throw error;
  } finally {
    if (serial) await restoreEmulator(tools, serial);
  }
}

async function plan(options) {
  const registry = await loadRegistry("mobile");
  const manifest = {
    ...registry,
    scenarios: scenariosForPlatform(registry, options.variant),
  };
  printPlan(
    options.variant,
    await planFlows(manifest, {
      platform: options.variant,
      metroPlatform: "android",
      mechanics: androidMechanics,
      extras: [await nativeInputFingerprint()],
      captureAll: options.all || captureAllRequested(),
    }),
  );
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  setGentleMode(options.gentle);
  if (options.command === "plan") {
    await plan(options);
    return;
  }
  await capture(options);
}

const isDirectRun =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isDirectRun) {
  main().catch((error) => {
    console.error(`\nAndroid visual capture failed: ${error.message}`);
    process.exit(1);
  });
}
