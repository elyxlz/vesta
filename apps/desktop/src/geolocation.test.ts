import { describe, expect, it } from "vitest";
import {
  parseObjectPath,
  parseVariantNumber,
  parseWindowsFix,
  resolveNativeFix,
} from "./geolocation";

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

describe("gdbus parsing", () => {
  it("extracts an object path from a call reply", () => {
    expect(
      parseObjectPath("(objectpath '/org/freedesktop/GeoClue2/Client/1',)\n"),
    ).toBe("/org/freedesktop/GeoClue2/Client/1");
    expect(parseObjectPath("(<objectpath '/'>,)\n")).toBe("/");
    expect(parseObjectPath("()")).toBeNull();
  });

  it("extracts a number from a variant reply", () => {
    expect(parseVariantNumber("(<39.2238>,)\n")).toBe(39.2238);
    expect(parseVariantNumber("(<double -0.1278>,)\n")).toBe(-0.1278);
    expect(parseVariantNumber("(<'text'>,)")).toBeNull();
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

  it("raises the helper's own reason when it refuses on macOS", async () => {
    const run = () => Promise.reject(new Error("Command failed: denied"));
    await expect(
      resolveNativeFix("darwin", run, undefined, "/app/vesta-location"),
    ).rejects.toThrow("denied");
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

  it("raises the provider's reason when it is missing or refuses", async () => {
    const run = () => Promise.reject(new Error("gdbus: command not found"));
    await expect(resolveNativeFix("linux", run, instantSleep)).rejects.toThrow(
      "gdbus: command not found",
    );
    await expect(resolveNativeFix("win32", run)).rejects.toThrow(
      "gdbus: command not found",
    );
  });

  it("answers null on a platform with no provider", async () => {
    const run = () => Promise.reject(new Error("must not be called"));
    expect(await resolveNativeFix("freebsd", run)).toBeNull();
  });
});
