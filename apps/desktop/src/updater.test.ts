import { describe, expect, it } from "vitest";
import { isNewerVersion, selectLinuxAsset } from "./updater";

const asset = (name: string) => ({
  name,
  browser_download_url: `https://example.test/${name}`,
});

const RELEASE = [
  "Vesta_0.1.176_amd64.deb",
  "Vesta_0.1.176_arm64.deb",
  "Vesta_0.1.176_x86_64.rpm",
  "Vesta_0.1.176_aarch64.rpm",
  "Vesta_0.1.176_universal.dmg",
].map(asset);

const FOREIGN_ARCH = ["Vesta_0.1.176_armv7l.deb"].map(asset);

describe("linux release asset selection", () => {
  it.each([
    { assets: RELEASE, arch: "arm64", ext: ".deb", expected: "Vesta_0.1.176_arm64.deb" },
    { assets: RELEASE, arch: "x64", ext: ".deb", expected: "Vesta_0.1.176_amd64.deb" },
    { assets: RELEASE, arch: "arm64", ext: ".rpm", expected: "Vesta_0.1.176_aarch64.rpm" },
    { assets: RELEASE, arch: "x64", ext: ".rpm", expected: "Vesta_0.1.176_x86_64.rpm" },
    { assets: RELEASE, arch: "x64", ext: ".AppImage", expected: undefined },
    { assets: FOREIGN_ARCH, arch: "arm64", ext: ".deb", expected: undefined },
  ])("$arch $ext -> $expected", ({ assets, arch, ext, expected }) => {
    expect(selectLinuxAsset(assets, arch, ext)?.name).toBe(expected);
  });
});

describe("latest-channel version comparison", () => {
  it.each([
    { candidate: "0.1.180", current: "0.1.179", expected: true },
    { candidate: "0.2.0", current: "0.1.179", expected: true },
    { candidate: "1.0.0", current: "0.9.9", expected: true },
    { candidate: "0.1.179", current: "0.1.179", expected: false },
    { candidate: "0.1.178", current: "0.1.179", expected: false },
    { candidate: "0.1.9", current: "0.1.10", expected: false },
  ])(
    "$candidate newer than $current -> $expected",
    ({ candidate, current, expected }) => {
      expect(isNewerVersion(candidate, current)).toBe(expected);
    },
  );
});
