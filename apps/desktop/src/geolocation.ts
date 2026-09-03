import { execFile } from "node:child_process";
import { promisify } from "node:util";

// The one owner of native OS geolocation for the main process. The renderer's
// navigator.geolocation cannot be relied on: Chromium's CoreLocation provider on macOS stalls
// waiting for an authorization prompt Electron never raises, and the network provider needs a
// Google API key. So every platform resolves here: macOS through the bundled Swift CoreLocation
// helper (which raises the prompt itself, carrying the app's identity), Windows through the in-box
// WinRT Geolocator (PowerShell), Linux through GeoClue2 over the system D-Bus (gdbus). A
// platform with no provider answers null; a provider that fails (denied, timeout, no service)
// raises its own reason, and the renderer falls back to timezone-only either way.

export interface NativeFix {
  latitude: number;
  longitude: number;
  accuracyM: number | null;
}

// A step (one process spawn) never outlives this; the Windows one-shot gets the full budget.
const NATIVE_FIX_TIMEOUT_MS = 15_000;
const EXEC_TIMEOUT_MS = 5_000;
const LINUX_POLL_INTERVAL_MS = 500;

type Run = (command: string, args: string[]) => Promise<string>;

const execFileAsync = promisify(execFile);

// A failing provider explains itself on stderr (the helper's reason, PowerShell's exception,
// gdbus's D-Bus error); re-raise that text so the renderer can show why there is no fix.
async function runWithTimeout(
  command: string,
  args: string[],
  timeoutMs: number,
): Promise<string> {
  try {
    const { stdout } = await execFileAsync(command, args, {
      timeout: timeoutMs,
      windowsHide: true,
    });
    return stdout;
  } catch (error) {
    const stderr =
      typeof error === "object" &&
      error !== null &&
      "stderr" in error &&
      typeof error.stderr === "string"
        ? error.stderr.trim()
        : "";
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(stderr === "" ? message : `${message}: ${stderr}`, {
      cause: error,
    });
  }
}

// Culture-invariant "lat|lon|accuracy" so a comma-decimal locale cannot corrupt the numbers.
const WINDOWS_SCRIPT = [
  "$ErrorActionPreference='Stop';",
  "[Windows.Devices.Geolocation.Geolocator,Windows.Devices.Geolocation,ContentType=WindowsRuntime]|Out-Null;",
  "Add-Type -AssemblyName System.Runtime.WindowsRuntime;",
  "$asTask=([System.WindowsRuntimeSystemExtensions].GetMethods()|Where-Object {$_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'})[0];",
  "$g=New-Object Windows.Devices.Geolocation.Geolocator;",
  "$t=$asTask.MakeGenericMethod([Windows.Devices.Geolocation.Geoposition]).Invoke($null,@($g.GetGeopositionAsync()));",
  "$t.Wait()|Out-Null;",
  "$c=$t.Result.Coordinate;",
  "$i=[System.Globalization.CultureInfo]::InvariantCulture;",
  "Write-Output ($c.Point.Position.Latitude.ToString($i)+'|'+$c.Point.Position.Longitude.ToString($i)+'|'+$c.Accuracy.ToString($i))",
].join("");

export function parseWindowsFix(stdout: string): NativeFix | null {
  const parts = stdout.trim().split("|");
  if (parts.length !== 3) return null;
  const latitude = Number(parts[0]);
  const longitude = Number(parts[1]);
  const accuracy = Number(parts[2]);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  return {
    latitude,
    longitude,
    accuracyM: Number.isFinite(accuracy) ? accuracy : null,
  };
}

async function windowsFix(run: Run): Promise<NativeFix | null> {
  const stdout = await run("powershell.exe", [
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    WINDOWS_SCRIPT,
  ]);
  return parseWindowsFix(stdout);
}

const GEOCLUE_DEST = "org.freedesktop.GeoClue2";
const GEOCLUE_CLIENT = "org.freedesktop.GeoClue2.Client";
// GeoClue accuracy level EXACT: the daemon still answers with whatever its sources allow.
const GEOCLUE_ACCURACY_EXACT = "<uint32 8>";

function parseObjectPath(stdout: string): string | null {
  return /objectpath '([^']+)'/.exec(stdout)?.[1] ?? null;
}

function parseVariantNumber(stdout: string): number | null {
  const match = /<(?:double )?(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)>/i.exec(stdout);
  if (!match) return null;
  const value = Number(match[1]);
  return Number.isFinite(value) ? value : null;
}

function gdbus(run: Run, objectPath: string, args: string[]): Promise<string> {
  return run("gdbus", [
    "call",
    "--system",
    "--dest",
    GEOCLUE_DEST,
    "--object-path",
    objectPath,
    ...args,
  ]);
}

function clientProperty(
  run: Run,
  client: string,
  method: "Get" | "Set",
  args: string[],
): Promise<string> {
  return gdbus(run, client, [
    "--method",
    `org.freedesktop.DBus.Properties.${method}`,
    GEOCLUE_CLIENT,
    ...args,
  ]);
}

const defaultSleep = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));

// GetClient, identify, Start, poll the Location property until the daemon has a fix, read the
// coordinates off the location object, Stop. GeoClue signals a fix rather than answering one, and
// polling a property from a one-shot CLI is the whole event loop we need. Some distros authorize
// clients through an agent or a .desktop allow-list a bare DesktopId does not satisfy; there Start
// errors and this resolves null, so such a machine degrades to timezone-only.
async function linuxFix(
  run: Run,
  sleep: (ms: number) => Promise<void> = defaultSleep,
): Promise<NativeFix | null> {
  const managerReply = await gdbus(run, "/org/freedesktop/GeoClue2/Manager", [
    "--method",
    "org.freedesktop.GeoClue2.Manager.GetClient",
  ]);
  const client = parseObjectPath(managerReply);
  if (client === null) return null;
  await clientProperty(run, client, "Set", ["DesktopId", "<'vesta'>"]);
  await clientProperty(run, client, "Set", [
    "RequestedAccuracyLevel",
    GEOCLUE_ACCURACY_EXACT,
  ]);
  await gdbus(run, client, ["--method", `${GEOCLUE_CLIENT}.Start`]);
  try {
    const attempts = Math.floor(NATIVE_FIX_TIMEOUT_MS / LINUX_POLL_INTERVAL_MS);
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const reply = await clientProperty(run, client, "Get", ["Location"]);
      const location = parseObjectPath(reply);
      if (location !== null && location !== "/") {
        return await readLocation(run, location);
      }
      await sleep(LINUX_POLL_INTERVAL_MS);
    }
    return null;
  } finally {
    await gdbus(run, client, ["--method", `${GEOCLUE_CLIENT}.Stop`]).catch(
      () => undefined,
    );
  }
}

async function readLocation(
  run: Run,
  location: string,
): Promise<NativeFix | null> {
  const property = (name: string) =>
    gdbus(run, location, [
      "--method",
      "org.freedesktop.DBus.Properties.Get",
      "org.freedesktop.GeoClue2.Location",
      name,
    ]).then(parseVariantNumber);
  const [latitude, longitude, accuracy] = await Promise.all([
    property("Latitude"),
    property("Longitude"),
    property("Accuracy"),
  ]);
  if (latitude === null || longitude === null) return null;
  return { latitude, longitude, accuracyM: accuracy };
}

// The helper prints the same invariant "lat|lon|accuracy" line as the Windows script and exits
// non-zero on any failure, so the run rejecting is what a denied or timed-out fix looks like.
async function macFix(run: Run, helperPath: string): Promise<NativeFix | null> {
  return parseWindowsFix(await run(helperPath, []));
}

// Null means the platform has no provider or it answered nothing usable; a provider that failed
// outright throws, carrying its own reason, and the renderer decides how to surface that.
export async function resolveNativeFix(
  platform: NodeJS.Platform,
  run: Run,
  sleep?: (ms: number) => Promise<void>,
  macHelperPath?: string,
): Promise<NativeFix | null> {
  if (platform === "darwin" && macHelperPath !== undefined) {
    return macFix(run, macHelperPath);
  }
  if (platform === "win32") return windowsFix(run);
  if (platform === "linux") return linuxFix(run, sleep);
  return null;
}

// The one-shot providers (macOS helper, Windows script) own the full fix budget; the Linux walk is
// many short gdbus calls, each bounded on its own.
export function readNativeGeolocation(
  macHelperPath: string,
): Promise<NativeFix | null> {
  const run: Run = (command, args) =>
    runWithTimeout(
      command,
      args,
      process.platform === "linux" ? EXEC_TIMEOUT_MS : NATIVE_FIX_TIMEOUT_MS,
    );
  return resolveNativeFix(process.platform, run, undefined, macHelperPath);
}
