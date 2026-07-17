import { describe, expect, it } from "vitest";
import { selectLinuxAsset } from "./updater";

const RELEASE_ASSETS = [
  {
    name: "Vesta_0.1.176_amd64.deb",
    browser_download_url: "https://example.test/Vesta_0.1.176_amd64.deb",
  },
  {
    name: "Vesta_0.1.176_arm64.deb",
    browser_download_url: "https://example.test/Vesta_0.1.176_arm64.deb",
  },
  {
    name: "Vesta_0.1.176_x86_64.rpm",
    browser_download_url: "https://example.test/Vesta_0.1.176_x86_64.rpm",
  },
  {
    name: "Vesta_0.1.176_aarch64.rpm",
    browser_download_url: "https://example.test/Vesta_0.1.176_aarch64.rpm",
  },
  {
    name: "Vesta_0.1.176_universal.dmg",
    browser_download_url: "https://example.test/Vesta_0.1.176_universal.dmg",
  },
];

const NO_DEB_ASSETS = [
  {
    name: "Vesta_0.1.176_x86_64.rpm",
    browser_download_url: "https://example.test/Vesta_0.1.176_x86_64.rpm",
  },
  {
    name: "Vesta_0.1.176_universal.dmg",
    browser_download_url: "https://example.test/Vesta_0.1.176_universal.dmg",
  },
];

const FOREIGN_ARCH_ASSETS = [
  {
    name: "Vesta_0.1.176_armv7l.deb",
    browser_download_url: "https://example.test/Vesta_0.1.176_armv7l.deb",
  },
];

describe("linux release asset selection", () => {
  it.each([
    { arch: "arm64", extension: ".deb", expected: "Vesta_0.1.176_arm64.deb" },
    { arch: "x64", extension: ".deb", expected: "Vesta_0.1.176_amd64.deb" },
    { arch: "arm64", extension: ".rpm", expected: "Vesta_0.1.176_aarch64.rpm" },
    { arch: "x64", extension: ".rpm", expected: "Vesta_0.1.176_x86_64.rpm" },
  ])("picks $expected for $arch asking $extension", ({
    arch,
    extension,
    expected,
  }) => {
    expect(selectLinuxAsset(RELEASE_ASSETS, arch, extension)?.name).toBe(
      expected,
    );
  });

  it("returns the asset's download url alongside its name", () => {
    expect(selectLinuxAsset(RELEASE_ASSETS, "x64", ".deb")).toEqual({
      name: "Vesta_0.1.176_amd64.deb",
      browser_download_url: "https://example.test/Vesta_0.1.176_amd64.deb",
    });
  });

  it.each([
    { arch: "arm64", extension: ".deb" },
    { arch: "x64", extension: ".deb" },
  ])(
    "returns undefined for $arch when the release ships no $extension",
    ({ arch, extension }) => {
      expect(selectLinuxAsset(NO_DEB_ASSETS, arch, extension)).toBeUndefined();
    },
  );

  it("returns undefined when no asset matches the arch", () => {
    expect(selectLinuxAsset(FOREIGN_ARCH_ASSETS, "arm64", ".deb")).toBeUndefined();
  });

  it("returns undefined for an empty asset list", () => {
    expect(selectLinuxAsset([], "x64", ".deb")).toBeUndefined();
  });
});
