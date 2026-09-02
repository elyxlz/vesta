import { app } from "electron";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import { createWriteStream } from "node:fs";
import path from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";

const GITHUB_OWNER = "elyxlz";
const GITHUB_REPO = "vesta";
const API_LATEST = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest`;

/**
 * Manual self-update to the latest published release. The app is a drifting client of vestad
 * (compatibility is decided by the /sync served version window, not version equality), so an
 * update is never automatic: the App Settings "Updates" card and the AppBehindScreen drive
 * check -> download -> relaunch on an explicit click, so the app never silently runs ahead of the
 * user's gateway. Up only, like the release channel it tracks.
 */
export interface AppUpdateStatus {
  available: boolean;
  version: string | null;
}

// electron-updater is CommonJS; its exports come through under `.default`. It is a singleton, so
// one configured instance carries state across check -> download -> install within a run.
async function autoUpdater() {
  const { autoUpdater: updater } = (await import("electron-updater")).default;
  updater.autoDownload = false;
  updater.autoInstallOnAppQuit = false;
  updater.allowDowngrade = false;
  updater.setFeedURL({
    provider: "github",
    owner: GITHUB_OWNER,
    repo: GITHUB_REPO,
  });
  return updater;
}

/** Check for a newer stable release without downloading it. Fails closed (no update on error). */
export async function getAppUpdate(): Promise<AppUpdateStatus> {
  try {
    if (process.platform === "linux") {
      const latest = await fetchLatestRelease();
      const available = isNewerVersion(latest.version, app.getVersion());
      return { available, version: available ? latest.version : null };
    }
    const updater = await autoUpdater();
    const result = await updater.checkForUpdates();
    const version = result?.updateInfo.version;
    if (version !== undefined && isNewerVersion(version, app.getVersion()))
      return { available: true, version };
    return { available: false, version: null };
  } catch (err) {
    console.error("app update check failed:", err);
    return { available: false, version: null };
  }
}

/**
 * Download the pending update, reporting progress as a 0-100 percentage. On macOS/Windows the
 * downloaded package is staged for install; on Linux it is installed in place via the OS package
 * manager. Resolves when the update is ready to take effect on the next relaunch.
 */
export async function downloadAppUpdate(
  onProgress: (percent: number) => void,
): Promise<void> {
  if (process.platform === "linux") {
    await updateLinuxToLatest(onProgress);
    return;
  }
  const updater = await autoUpdater();
  updater.removeAllListeners("download-progress");
  updater.on("download-progress", (progress: { percent: number }) => {
    onProgress(progress.percent);
  });
  await updater.checkForUpdates();
  await updater.downloadUpdate();
}

/** Relaunch into the downloaded update. macOS/Windows install on quit; Linux is already installed. */
export async function quitAndInstallUpdate(): Promise<void> {
  if (process.platform === "linux") {
    app.relaunch();
    app.quit();
    return;
  }
  const updater = await autoUpdater();
  updater.quitAndInstall();
}

function run(
  command: string,
  args: string[],
): Promise<{ code: number; stderr: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: ["ignore", "ignore", "pipe"] });
    let stderr = "";
    child.stderr.on("data", (chunk: Buffer) => (stderr += chunk.toString()));
    child.on("error", reject);
    child.on("close", (code) => {
      resolve({ code: code ?? 1, stderr });
    });
  });
}

async function commandExists(command: string): Promise<boolean> {
  try {
    return (await run(command, ["--version"])).code === 0;
  } catch {
    return false;
  }
}

interface ReleaseAsset {
  name: string;
  browser_download_url: string;
}

function isReleaseAsset(value: unknown): value is ReleaseAsset {
  return (
    typeof value === "object" &&
    value !== null &&
    "name" in value &&
    typeof value.name === "string" &&
    "browser_download_url" in value &&
    typeof value.browser_download_url === "string"
  );
}

export function selectLinuxAsset(
  assets: ReleaseAsset[],
  arch: string,
  extension: string,
): ReleaseAsset | undefined {
  const archTokens =
    arch === "arm64" ? ["arm64", "aarch64"] : ["x64", "amd64", "x86_64"];
  return assets.find(
    (candidate) =>
      candidate.name.endsWith(extension) &&
      archTokens.some((token) => candidate.name.includes(token)),
  );
}

/** True when `candidate` is a strictly newer dotted version than `current`. Prerelease
 * suffixes are ignored; the latest-release feed only serves stable versions.
 * Deliberately duplicated from @vesta/core's compareReleaseVersions across the process boundary
 * (like the preload dual-declaration): the Electron main process ships only electron-updater and is
 * compiled with plain tsc into app.asar, so a @vesta/core workspace dependency would not resolve at
 * runtime, and core's fail-open-to-null semantics differ from this feed's lenient parse. */
export function isNewerVersion(candidate: string, current: string): boolean {
  const parts = (version: string): number[] =>
    version.split(".").map((token) => Number.parseInt(token, 10) || 0);
  const left = parts(candidate);
  const right = parts(current);
  for (let index = 0; index < Math.max(left.length, right.length); index++) {
    const diff = (left[index] ?? 0) - (right[index] ?? 0);
    if (diff !== 0) return diff > 0;
  }
  return false;
}

interface LatestRelease {
  version: string;
  assets: ReleaseAsset[];
}

/** Resolve the latest stable release's version + assets from the GitHub API. */
async function fetchLatestRelease(): Promise<LatestRelease> {
  const response = await fetch(API_LATEST);
  if (!response.ok)
    throw new Error(`latest release not found (${String(response.status)})`);
  const release: unknown = await response.json();
  if (
    release === null ||
    typeof release !== "object" ||
    !("tag_name" in release) ||
    typeof release.tag_name !== "string" ||
    !("assets" in release) ||
    !Array.isArray(release.assets)
  )
    throw new Error("malformed latest release response");
  const assets: unknown[] = release.assets;
  return {
    version: release.tag_name.replace(/^v/, ""),
    assets: assets.filter(isReleaseAsset),
  };
}

async function updateLinuxToLatest(
  onProgress: (percent: number) => void,
): Promise<void> {
  const dpkg = await commandExists("dpkg");
  const rpm = !dpkg && (await commandExists("rpm"));
  if (!dpkg && !rpm)
    throw new Error("no supported package manager (dpkg/rpm) found");

  const latest = await fetchLatestRelease();
  if (!isNewerVersion(latest.version, app.getVersion())) return;

  const extension = dpkg ? ".deb" : ".rpm";
  const asset = selectLinuxAsset(latest.assets, process.arch, extension);
  if (!asset)
    throw new Error(
      `no ${extension} for ${process.arch} in release v${latest.version}`,
    );

  const tmpDir = path.join(app.getPath("temp"), "vesta-update");
  await fs.mkdir(tmpDir, { recursive: true });
  const packagePath = path.join(
    tmpDir,
    path.basename(new URL(asset.browser_download_url).pathname),
  );

  const download = await fetch(asset.browser_download_url);
  if (!download.ok || !download.body)
    throw new Error(`download failed (${String(download.status)})`);
  const total = Number(download.headers.get("content-length") ?? 0);
  let received = 0;
  const source = Readable.fromWeb(download.body);
  if (total > 0)
    source.on("data", (chunk: Buffer) => {
      received += chunk.length;
      onProgress((received / total) * 100);
    });
  await pipeline(source, createWriteStream(packagePath));

  // pkexec drives the GUI privilege-escalation prompt
  const installArgs = dpkg
    ? ["dpkg", "-i", packagePath]
    : ["rpm", "-U", "--force", packagePath];
  const result = await run("pkexec", installArgs);
  await fs.rm(tmpDir, { recursive: true, force: true });
  if (result.code !== 0) throw new Error(`install failed: ${result.stderr}`);
}
