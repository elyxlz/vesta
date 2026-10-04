// Where each app comes from. Desktop files carry the release version in their names
// (apps/desktop/electron-builder.yml), so they come from the release this bundle shipped in, which
// is the serving gateway's own version and so always inside its client window. The Android APK
// keeps one name on every release, so it comes from the latest one.
const RELEASES_URL = "https://github.com/elyxlz/vesta/releases";

export interface AppDownload {
  platform: string;
  detail: string;
  url: string;
}

export function desktopDownloads(version: string): AppDownload[] {
  const file = (name: string) =>
    `${RELEASES_URL}/download/v${version}/Vesta_${version}_${name}`;
  return [
    { platform: "macOS", detail: "Apple Silicon", url: file("arm64.dmg") },
    { platform: "Windows", detail: "x64", url: file("x64.exe") },
    { platform: "Linux", detail: ".deb, x64", url: file("amd64.deb") },
    { platform: "Linux", detail: ".rpm, x64", url: file("x86_64.rpm") },
  ];
}

export const ANDROID_DOWNLOAD: AppDownload = {
  platform: "Android",
  detail: ".apk",
  url: `${RELEASES_URL}/latest/download/vesta-android.apk`,
};

export function allDownloadsUrl(version: string): string {
  return `${RELEASES_URL}/tag/v${version}`;
}
