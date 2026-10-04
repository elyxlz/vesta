import { describe, expect, it } from "vitest";
import {
  ANDROID_DOWNLOAD,
  otherVersionsUrl,
  computerDownloads,
} from "./app-downloads";

describe("app downloads", () => {
  it("names every desktop file of the given release", () => {
    expect(computerDownloads("0.3.15").map((download) => download.url)).toEqual(
      [
        "https://github.com/elyxlz/vesta/releases/download/v0.3.15/Vesta_0.3.15_arm64.dmg",
        "https://github.com/elyxlz/vesta/releases/download/v0.3.15/Vesta_0.3.15_x64.exe",
        "https://github.com/elyxlz/vesta/releases/download/v0.3.15/Vesta_0.3.15_amd64.deb",
        "https://github.com/elyxlz/vesta/releases/download/v0.3.15/Vesta_0.3.15_x86_64.rpm",
      ],
    );
  });

  it("takes the android apk from the latest release", () => {
    expect(ANDROID_DOWNLOAD.url).toBe(
      "https://github.com/elyxlz/vesta/releases/latest/download/vesta-android.apk",
    );
  });

  it("links the release page for other versions", () => {
    expect(otherVersionsUrl("0.3.15")).toBe(
      "https://github.com/elyxlz/vesta/releases/tag/v0.3.15",
    );
  });
});
