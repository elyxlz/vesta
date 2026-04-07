import { useEffect, useState } from "react";
import { detectPlatform, type Platform } from "@/lib/platform";

const REPO = "https://github.com/elyxlz/vesta";
const RELEASES = `${REPO}/releases`;

type DownloadInfo = {
  label: string;
  filename: (version: string) => string;
  note?: string;
  altLinks?: { label: string; filename: (version: string) => string }[];
};

const DOWNLOAD_MAP: Record<Platform, DownloadInfo> = {
  macos: {
    label: "Download for macOS",
    filename: (v) => `Vesta_${v}_aarch64.dmg`,
    note: "Apple Silicon",
    altLinks: [{ label: "Intel Mac", filename: (v) => `Vesta_${v}_x64.dmg` }],
  },
  windows: {
    label: "Download for Windows",
    filename: (v) => `Vesta_${v}_x64-setup.exe`,
  },
  linux: {
    label: "Download for Linux",
    filename: (v) => `Vesta_${v}_amd64.deb`,
    note: ".deb",
    altLinks: [
      { label: ".rpm", filename: (v) => `Vesta-${v}-1.x86_64.rpm` },
      { label: "ARM64 .deb", filename: (v) => `Vesta_${v}_arm64.deb` },
    ],
  },
  android: {
    label: "Download for Android",
    filename: (v) => `Vesta_${v}.apk`,
    note: ".apk",
  },
  ios: {
    label: "Get on TestFlight",
    filename: () => "",
    note: "Coming soon",
  },
};

const ALL_PLATFORMS: { label: string; platform: Platform }[] = [
  { label: "macOS", platform: "macos" },
  { label: "Windows", platform: "windows" },
  { label: "Linux", platform: "linux" },
  { label: "Android", platform: "android" },
  { label: "iOS", platform: "ios" },
];

function buildUrl(version: string, filename: string): string {
  return `${RELEASES}/download/v${version}/${filename}`;
}

export function Landing() {
  const platform = detectPlatform();
  const download = DOWNLOAD_MAP[platform];
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${RELEASES}/latest/download/latest.json`)
      .then((r) => r.json())
      .then((data: { version?: string }) => {
        if (data.version) setVersion(data.version);
      })
      .catch(() => {});
  }, []);

  const mainUrl = version
    ? buildUrl(version, download.filename(version))
    : `${RELEASES}/latest`;

  return (
    <div className="flex flex-col items-center justify-center flex-1 min-h-0 px-4 gap-8 select-none">
      <div className="flex flex-col items-center gap-2">
        <h1 className="text-4xl font-serif font-medium tracking-tight">
          Vesta
        </h1>
        <p className="text-sm text-muted-foreground">Personal AI assistant</p>
      </div>

      <div className="flex flex-col items-center gap-3">
        <a
          href={mainUrl}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          {download.label}
          {download.note && (
            <span className="text-xs opacity-70">({download.note})</span>
          )}
        </a>

        {version && download.altLinks && (
          <div className="flex gap-3">
            {download.altLinks.map((link) => (
              <a
                key={link.label}
                href={buildUrl(version, link.filename(version))}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors underline underline-offset-2"
              >
                {link.label}
              </a>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-wrap justify-center gap-3 text-xs text-muted-foreground">
        {ALL_PLATFORMS.filter((p) => p.platform !== platform).map((p) => {
          const info = DOWNLOAD_MAP[p.platform];
          const url = version
            ? buildUrl(version, info.filename(version))
            : `${RELEASES}/latest`;
          return (
            <a
              key={p.platform}
              href={url}
              className="hover:text-foreground transition-colors underline underline-offset-2"
            >
              {p.label}
            </a>
          );
        })}
      </div>
    </div>
  );
}
