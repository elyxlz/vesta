import type { Platform } from "@/lib/platform";

// Where each app comes from. Desktop files carry the release version in their names
// (apps/desktop/electron-builder.yml), so they come from the release this bundle shipped in, which
// is the serving gateway's own version and so always inside its client window. The Android APK
// keeps one name on every release, so it comes from the latest one.
const RELEASES_URL = "https://github.com/elyxlz/vesta/releases";

export interface AppChoice {
  label: string;
  url: string;
}

// One tile per platform. No choices means the app is not out yet; more than one means the tile
// asks which (Linux ships one package per distribution family).
export interface AppTile {
  platform: Platform;
  name: string;
  hint: string | null;
  choices: AppChoice[];
}

export function appTiles(version: string): AppTile[] {
  const file = (name: string) =>
    `${RELEASES_URL}/download/v${version}/Vesta_${version}_${name}`;
  return [
    {
      platform: "macos",
      name: "Mac",
      hint: "M1 or newer",
      choices: [{ label: "Mac", url: file("arm64.dmg") }],
    },
    {
      platform: "windows",
      name: "Windows",
      hint: null,
      choices: [{ label: "Windows", url: file("x64.exe") }],
    },
    {
      platform: "linux",
      name: "Linux",
      hint: null,
      choices: [
        { label: "Ubuntu, Debian", url: file("amd64.deb") },
        { label: "Fedora", url: file("x86_64.rpm") },
      ],
    },
    {
      platform: "android",
      name: "Android",
      hint: null,
      choices: [
        {
          label: "Android",
          url: `${RELEASES_URL}/latest/download/vesta-android.apk`,
        },
      ],
    },
    { platform: "ios", name: "iPhone", hint: "coming soon", choices: [] },
  ];
}
