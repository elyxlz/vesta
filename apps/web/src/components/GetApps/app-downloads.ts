import type { Platform } from "@/lib/platform";

// Where each app comes from. Desktop files carry the release version in their names
// (apps/desktop/electron-builder.yml), so they come from the release this bundle shipped in, which
// is the serving gateway's own version and so always inside its client window. The Android APK
// keeps one name on every release, so it comes from the latest one.
const RELEASES_URL = "https://github.com/elyxlz/vesta/releases";

export interface AppDownload {
  platform: Platform;
  name: string;
  hint: string | null;
  url: string;
}

export function computerDownloads(version: string): AppDownload[] {
  const file = (name: string) =>
    `${RELEASES_URL}/download/v${version}/Vesta_${version}_${name}`;
  return [
    {
      platform: "macos",
      name: "Mac",
      hint: "M1 or newer",
      url: file("arm64.dmg"),
    },
    { platform: "windows", name: "Windows", hint: null, url: file("x64.exe") },
    {
      platform: "linux",
      name: "Linux",
      hint: "Ubuntu, Debian",
      url: file("amd64.deb"),
    },
    {
      platform: "linux",
      name: "Linux",
      hint: "Fedora",
      url: file("x86_64.rpm"),
    },
  ];
}

export const ANDROID_DOWNLOAD: AppDownload = {
  platform: "android",
  name: "Android",
  hint: null,
  url: `${RELEASES_URL}/latest/download/vesta-android.apk`,
};

export function otherVersionsUrl(version: string): string {
  return `${RELEASES_URL}/tag/v${version}`;
}
