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
 * Self-update to the latest published release. The app is a drifting client of vestad
 * (compatibility is decided by the /sync served version window, not version equality), so it
 * tracks the latest release on its own, up only, independent of the gateway's version.
 * On macOS/Windows the download happens in the background and installs on the next quit;
 * Linux resolves and installs the matching package in place.
 */
export async function checkForAppUpdate(): Promise<void> {
  if (process.platform === "linux") {
    await updateLinuxToLatest();
    return;
  }
  // electron-updater is CommonJS; its exports come through under `.default`.
  const { autoUpdater } = (await import("electron-updater")).default;
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.allowDowngrade = false;
  // With autoDownload, checkForUpdates() resolves at the metadata fetch and the download runs
  // in the background; its failure surfaces only as an EventEmitter "error" event, which throws
  // if unhandled. Swallow it so a mid-download network blip (or an offline launch) stays silent.
  autoUpdater.on("error", (err) => {
    console.error("app auto-update failed:", err);
  });
  autoUpdater.setFeedURL({
    provider: "github",
    owner: GITHUB_OWNER,
    repo: GITHUB_REPO,
  });
  await autoUpdater.checkForUpdates();
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
    !("assets" in release)
  )
    throw new Error("malformed latest release response");
  const tag = (release as { tag_name: string }).tag_name;
  const assets = (release as { assets: ReleaseAsset[] }).assets;
  return { version: tag.replace(/^v/, ""), assets };
}

async function updateLinuxToLatest(): Promise<void> {
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
  await pipeline(Readable.fromWeb(download.body), createWriteStream(packagePath));

  // pkexec drives the GUI privilege-escalation prompt
  const installArgs = dpkg
    ? ["dpkg", "-i", packagePath]
    : ["rpm", "-U", "--force", packagePath];
  const result = await run("pkexec", installArgs);
  await fs.rm(tmpDir, { recursive: true, force: true });
  if (result.code !== 0) throw new Error(`install failed: ${result.stderr}`);
}
