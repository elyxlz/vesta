import { app } from "electron";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import { createWriteStream } from "node:fs";
import path from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";

const RELEASE_BASE = "https://github.com/elyxlz/vesta/releases";
const API_BASE = "https://api.github.com/repos/elyxlz/vesta/releases";

/**
 * Converge the app onto the gateway's exact version (the gateway may be on a
 * beta that releases/latest never points at, so the feed targets the version's
 * own release assets).
 */
export async function installAppUpdate(version: string): Promise<void> {
  if (process.platform === "linux") {
    await installLinuxPackage(version);
    return;
  }
  const { autoUpdater } = await import("electron-updater");
  autoUpdater.autoDownload = false;
  autoUpdater.allowDowngrade = true;
  autoUpdater.setFeedURL({
    provider: "generic",
    url: `${RELEASE_BASE}/download/v${version}`,
  });
  const result = await autoUpdater.checkForUpdates();
  if (!result) throw new Error("updater unavailable in this build");
  await autoUpdater.downloadUpdate();
  autoUpdater.quitAndInstall();
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
    child.on("close", (code) => resolve({ code: code ?? 1, stderr }));
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

/** Pick this arch's .deb or .rpm from the release's asset list by name. */
async function findLinuxAsset(
  version: string,
  extension: string,
): Promise<string> {
  const response = await fetch(`${API_BASE}/tags/v${version}`);
  if (!response.ok)
    throw new Error(`release v${version} not found (${response.status})`);
  const release: unknown = await response.json();
  const assets =
    release !== null && typeof release === "object" && "assets" in release
      ? (release as { assets: ReleaseAsset[] }).assets
      : [];
  const archTokens =
    process.arch === "arm64"
      ? ["arm64", "aarch64"]
      : ["x64", "amd64", "x86_64"];
  const asset = assets.find(
    (candidate) =>
      candidate.name.endsWith(extension) &&
      archTokens.some((token) => candidate.name.includes(token)),
  );
  if (!asset)
    throw new Error(
      `no ${extension} for ${process.arch} in release v${version}`,
    );
  return asset.browser_download_url;
}

async function installLinuxPackage(version: string): Promise<void> {
  const dpkg = await commandExists("dpkg");
  const rpm = !dpkg && (await commandExists("rpm"));
  if (!dpkg && !rpm)
    throw new Error("no supported package manager (dpkg/rpm) found");

  const url = await findLinuxAsset(version, dpkg ? ".deb" : ".rpm");
  const tmpDir = path.join(app.getPath("temp"), "vesta-update");
  await fs.mkdir(tmpDir, { recursive: true });
  const packagePath = path.join(tmpDir, path.basename(new URL(url).pathname));

  const download = await fetch(url);
  if (!download.ok || !download.body)
    throw new Error(`download failed (${download.status})`);
  await pipeline(Readable.fromWeb(download.body), createWriteStream(packagePath));

  // pkexec drives the GUI privilege-escalation prompt
  const installArgs = dpkg
    ? ["dpkg", "-i", packagePath]
    : ["rpm", "-U", "--force", packagePath];
  const result = await run("pkexec", installArgs);
  await fs.rm(tmpDir, { recursive: true, force: true });
  if (result.code !== 0) throw new Error(`install failed: ${result.stderr}`);
}
