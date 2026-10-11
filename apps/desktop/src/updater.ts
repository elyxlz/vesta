import { autoUpdater as squirrelMac } from "electron";
import { autoUpdater } from "electron-updater";

/**
 * Manual self-update to the latest published release. The app is a drifting client of vestad
 * (compatibility is decided by the /sync served version window, not version equality), so an
 * update is never automatic: the App Settings "Updates" card and the AppBehindScreen drive
 * check -> download -> relaunch on an explicit click, so the app never silently runs ahead of the
 * user's gateway. Up only, like the release channel it tracks.
 *
 * electron-updater owns the whole decision: the feed comes from the app-update.yml electron-builder
 * bakes into Resources (the GitHub provider derived from package.json's repository), the platform
 * updater (MacUpdater, NsisUpdater, DebUpdater, RpmUpdater) reads that release's latest*.yml, and
 * isUpdateAvailable is its semver comparison against the running version.
 */
export interface AppUpdateStatus {
  available: boolean;
  version: string | null;
}

// electron-updater's autoUpdater is a singleton, so one configured instance carries state across
// check -> download -> install within a run.
function updater(): typeof autoUpdater {
  autoUpdater.autoDownload = false;
  // On macOS this flag is what hands the download to Squirrel.Mac for staging; the install still
  // waits for the relaunch click. Elsewhere it would install silently on quit.
  autoUpdater.autoInstallOnAppQuit = process.platform === "darwin";
  autoUpdater.allowDowngrade = false;
  return autoUpdater;
}

/** Check for a newer stable release without downloading it. Fails closed (no update on error). */
export async function getAppUpdate(): Promise<AppUpdateStatus> {
  try {
    const result = await updater().checkForUpdates();
    if (result?.isUpdateAvailable)
      return { available: true, version: result.updateInfo.version };
    return { available: false, version: null };
  } catch (err) {
    console.error("app update check failed:", err);
    return { available: false, version: null };
  }
}

/**
 * Squirrel.Mac installs from its own staged copy: it unpacks and verifies the zip electron-updater
 * serves it, and until then quitAndInstall silently waits. Resolves once that copy is staged.
 */
function squirrelStaged(): Promise<void> {
  return new Promise((resolve, reject) => {
    const onStaged = () => {
      squirrelMac.off("error", onError);
      resolve();
    };
    const onError = (error: Error) => {
      squirrelMac.off("update-downloaded", onStaged);
      reject(error);
    };
    squirrelMac.once("update-downloaded", onStaged);
    squirrelMac.once("error", onError);
  });
}

/**
 * Download the pending update, reporting progress as a 0-100 percentage. Resolves only once the
 * update can install at once, so the relaunch click quits immediately on every platform; nothing
 * changes until quitAndInstallUpdate.
 */
export async function downloadAppUpdate(
  onProgress: (percent: number) => void,
): Promise<void> {
  const instance = updater();
  instance.removeAllListeners("download-progress");
  instance.on("download-progress", (progress: { percent: number }) => {
    onProgress(progress.percent);
  });
  await instance.checkForUpdates();
  if (process.platform !== "darwin") {
    await instance.downloadUpdate();
    return;
  }
  await Promise.all([squirrelStaged(), instance.downloadUpdate()]);
}

/**
 * Relaunch into the downloaded update. macOS and Windows install on quit; Linux installs the
 * package through the package manager behind the OS privilege prompt, then relaunches.
 */
export function quitAndInstallUpdate(): void {
  updater().quitAndInstall();
}
