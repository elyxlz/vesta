import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  parseWindowsFix,
  readNativeGeolocation,
  resolveNativeFix,
} from "./geolocation";

const instantSleep = () => Promise.resolve();

const CLIENT = "/org/freedesktop/GeoClue2/Client/7";
const LOCATION = "/org/freedesktop/GeoClue2/Location/0";

// A GeoClue daemon fake: `location` is what the Location property answers, and `coordinates`
// the location object's properties, each keyed by the tail of the gdbus call.
function geoclue(
  calls: string[],
  location: (polls: number) => string,
  coordinates: Record<string, string> = {
    Latitude: "(<39.2238>,)",
    Longitude: "(<9.1217>,)",
    Accuracy: "(<25.0>,)",
  },
) {
  return (_command: string, args: string[]) => {
    const call = args.join(" ");
    calls.push(call);
    if (call.includes("Manager.GetClient")) {
      return Promise.resolve(`(objectpath '${CLIENT}',)`);
    }
    if (call.endsWith("Client Location")) {
      const polls = calls.filter((c) => c.endsWith("Client Location")).length;
      return Promise.resolve(`(<objectpath '${location(polls)}'>,)`);
    }
    const property = Object.keys(coordinates).find((name) =>
      call.endsWith(name),
    );
    return Promise.resolve(
      property === undefined ? "()" : (coordinates[property] ?? "()"),
    );
  };
}

describe("parseWindowsFix", () => {
  it("parses the invariant lat|lon|accuracy line", () => {
    expect(parseWindowsFix("39.2238|9.1217|25\r\n")).toEqual({
      latitude: 39.2238,
      longitude: 9.1217,
      accuracyM: 25,
    });
  });

  it("keeps the fix when only the accuracy is malformed", () => {
    expect(parseWindowsFix("39.2238|9.1217|NaN")).toEqual({
      latitude: 39.2238,
      longitude: 9.1217,
      accuracyM: null,
    });
  });

  it("rejects malformed output", () => {
    expect(parseWindowsFix("")).toBeNull();
    expect(parseWindowsFix("error: denied")).toBeNull();
    expect(parseWindowsFix("a|b|c")).toBeNull();
  });
});

describe("resolveNativeFix", () => {
  it("resolves a macOS fix through the bundled CoreLocation helper", async () => {
    const commands: string[][] = [];
    const run = (command: string, args: string[]) => {
      commands.push([command, ...args]);
      return Promise.resolve("39.2238|9.1217|25\n");
    };
    expect(
      await resolveNativeFix("darwin", run, undefined, "/app/vesta-location"),
    ).toEqual({
      latitude: 39.2238,
      longitude: 9.1217,
      accuracyM: 25,
    });
    expect(commands).toEqual([["/app/vesta-location"]]);
  });

  it("resolves a Windows fix through powershell", async () => {
    const commands: string[][] = [];
    const run = (command: string, args: string[]) => {
      commands.push([command, ...args.slice(0, 2)]);
      return Promise.resolve("51.5074|-0.1278|30");
    };
    expect(await resolveNativeFix("win32", run)).toEqual({
      latitude: 51.5074,
      longitude: -0.1278,
      accuracyM: 30,
    });
    expect(commands).toEqual([
      ["powershell.exe", "-NoProfile", "-NonInteractive"],
    ]);
  });

  it("walks the GeoClue client to a fix on Linux and stops it after", async () => {
    const calls: string[] = [];
    // First poll: no fix yet; second poll: the location object exists.
    const run = geoclue(calls, (polls) => (polls === 1 ? "/" : LOCATION));
    expect(await resolveNativeFix("linux", run, instantSleep)).toEqual({
      latitude: 39.2238,
      longitude: 9.1217,
      accuracyM: 25,
    });
    expect(calls.some((c) => c.includes("Client.Start"))).toBe(true);
    expect(calls.at(-1)).toContain("Client.Stop");
  });

  it("gives up on Linux when the daemon never answers a fix, and still stops the client", async () => {
    const calls: string[] = [];
    const run = geoclue(calls, () => "/");
    expect(await resolveNativeFix("linux", run, instantSleep)).toBeNull();
    expect(calls.at(-1)).toContain("Client.Stop");
  });

  it("answers null on Linux when the location object has no latitude", async () => {
    const calls: string[] = [];
    const run = geoclue(calls, () => LOCATION, { Longitude: "(<9.1217>,)" });
    expect(await resolveNativeFix("linux", run, instantSleep)).toBeNull();
  });

  it("answers null on macOS with no helper bundled", async () => {
    const run = () => Promise.reject(new Error("must not be called"));
    expect(await resolveNativeFix("darwin", run)).toBeNull();
  });

  it.each<{
    name: string;
    reason: string;
    call: (
      run: (command: string, args: string[]) => Promise<string>,
    ) => Promise<unknown>;
  }>([
    {
      name: "the macOS helper refuses",
      reason: "denied",
      call: (run) =>
        resolveNativeFix("darwin", run, undefined, "/app/vesta-location"),
    },
    {
      name: "the Linux provider is missing or refuses",
      reason: "gdbus: command not found",
      call: (run) => resolveNativeFix("linux", run, instantSleep),
    },
    {
      name: "the Windows provider is missing or refuses",
      reason: "gdbus: command not found",
      call: (run) => resolveNativeFix("win32", run),
    },
  ])(
    "raises the provider's own reason when $name",
    async ({ reason, call }) => {
      const run = () => Promise.reject(new Error(reason));
      await expect(call(run)).rejects.toThrow(reason);
    },
  );

  it("answers null on a platform with no provider", async () => {
    const run = () => Promise.reject(new Error("must not be called"));
    expect(await resolveNativeFix("freebsd", run)).toBeNull();
  });
});

describe("readNativeGeolocation", () => {
  const platform = Object.getOwnPropertyDescriptor(process, "platform");
  let helperDir = "";

  afterEach(async () => {
    if (platform) Object.defineProperty(process, "platform", platform);
    await fs.rm(helperDir, { recursive: true, force: true });
  });

  it("re-raises a failing provider's stderr as the reason", async () => {
    helperDir = await fs.mkdtemp(path.join(os.tmpdir(), "vesta-geo-test-"));
    const helper = path.join(helperDir, "vesta-location");
    await fs.writeFile(
      helper,
      "#!/bin/sh\necho 'location access denied' >&2\nexit 1\n",
      {
        mode: 0o755,
      },
    );
    Object.defineProperty(process, "platform", {
      value: "darwin",
      configurable: true,
    });

    await expect(readNativeGeolocation(helper)).rejects.toThrow(
      "location access denied",
    );
  });
});
