import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mobileRoot = path.dirname(fileURLToPath(import.meta.url));
const appsRoot = path.resolve(mobileRoot, "..");
const lockfile = JSON.parse(
  fs.readFileSync(path.join(appsRoot, "package-lock.json"), "utf8"),
);
const mobilePackage = JSON.parse(
  fs.readFileSync(path.join(mobileRoot, "package.json"), "utf8"),
);

function packageLocations(packageName) {
  const suffix = `node_modules/${packageName}`;

  return Object.entries(lockfile.packages)
    .filter(([location, metadata]) => {
      return location.endsWith(suffix) && typeof metadata.version === "string";
    })
    .map(([location, metadata]) => ({
      location,
      version: metadata.version,
    }));
}

describe("mobile monorepo dependencies", () => {
  it("installs mobile and core as linked workspaces", () => {
    expect(lockfile.packages[""].workspaces).toContain("mobile");
    expect(lockfile.packages.mobile.dependencies["@vesta/core"]).toBe("*");
    expect(lockfile.packages["node_modules/@vesta/mobile"]).toMatchObject({
      link: true,
      resolved: "mobile",
    });
    expect(lockfile.packages["node_modules/@vesta/core"]).toMatchObject({
      link: true,
      resolved: "core",
    });
  });

  it.each(["react", "react-dom", "react-native"])(
    "keeps one hoisted %s installation",
    (packageName) => {
      expect(packageLocations(packageName)).toEqual([
        {
          location: `node_modules/${packageName}`,
          version: mobilePackage.dependencies[packageName],
        },
      ]);
    },
  );

  it("hoists Expo Router beside the Expo CLI used for typed routes", () => {
    const locations = packageLocations("expo-router");

    expect(locations).toHaveLength(1);
    expect(locations[0].location).toBe("node_modules/expo-router");
  });
});
