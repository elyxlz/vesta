import { describe, expect, it } from "vitest";
import { appTiles } from "./app-downloads";

describe("app tiles", () => {
  it("links each platform to its file", () => {
    expect(
      appTiles("0.3.15").map((tile) => [
        tile.platform,
        tile.choices.map((choice) => choice.url),
      ]),
    ).toEqual([
      [
        "macos",
        [
          "https://github.com/elyxlz/vesta/releases/download/v0.3.15/Vesta_0.3.15_arm64.dmg",
        ],
      ],
      [
        "windows",
        [
          "https://github.com/elyxlz/vesta/releases/download/v0.3.15/Vesta_0.3.15_x64.exe",
        ],
      ],
      [
        "linux",
        [
          "https://github.com/elyxlz/vesta/releases/download/v0.3.15/Vesta_0.3.15_amd64.deb",
          "https://github.com/elyxlz/vesta/releases/download/v0.3.15/Vesta_0.3.15_x86_64.rpm",
        ],
      ],
      [
        "android",
        [
          "https://github.com/elyxlz/vesta/releases/latest/download/vesta-android.apk",
        ],
      ],
      ["ios", []],
    ]);
  });
});
