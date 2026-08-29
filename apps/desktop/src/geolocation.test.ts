import { describe, expect, it } from "vitest";
import { parseWindowsFix, resolveNativeFix } from "./geolocation";

const instantSleep = () => Promise.resolve();

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
    const client = "/org/freedesktop/GeoClue2/Client/7";
    const location = "/org/freedesktop/GeoClue2/Location/0";
    const run = (_command: string, args: string[]) => {
      const call = args.join(" ");
      calls.push(call);
      if (call.includes("Manager.GetClient")) {
        return Promise.resolve(`(objectpath '${client}',)`);
      }
      if (call.endsWith("Client Location")) {
        // First poll: no fix yet; second poll: the location object exists.
        const polls = calls.filter((c) => c.endsWith("Client Location")).length;
        return Promise.resolve(
          polls === 1 ? "(<objectpath '/'>,)" : `(<objectpath '${location}'>,)`,
        );
      }
      if (call.endsWith("Latitude")) return Promise.resolve("(<39.2238>,)");
      if (call.endsWith("Longitude")) return Promise.resolve("(<9.1217>,)");
      if (call.endsWith("Accuracy")) return Promise.resolve("(<25.0>,)");
      return Promise.resolve("()");
    };
    expect(await resolveNativeFix("linux", run, instantSleep)).toEqual({
      latitude: 39.2238,
      longitude: 9.1217,
      accuracyM: 25,
    });
    expect(calls.some((c) => c.includes("Client.Start"))).toBe(true);
    expect(calls.at(-1)).toContain("Client.Stop");
  });

  it.each<{
    name: string;
    reason: string;
    call: (run: (command: string, args: string[]) => Promise<string>) => Promise<unknown>;
  }>([
    {
      name: "the macOS helper refuses",
      reason: "denied",
      call: (run) => resolveNativeFix("darwin", run, undefined, "/app/vesta-location"),
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
  ])("raises the provider's own reason when $name", async ({ reason, call }) => {
    const run = () => Promise.reject(new Error(reason));
    await expect(call(run)).rejects.toThrow(reason);
  });

  it("answers null on a platform with no provider", async () => {
    const run = () => Promise.reject(new Error("must not be called"));
    expect(await resolveNativeFix("freebsd", run)).toBeNull();
  });
});
