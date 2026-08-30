import { useEffect, useState } from "react";
import { authedUrl } from "@/lib/authed-url";

// How long to wait before re-attempting a URL build that failed (not connected yet, refresh
// hiccup): cheap, bounded per mounted element, and self-healing without any caller wiring.
const REBUILD_RETRY_MS = 3000;

// A media element's src for a gateway path: `<img>`/`<video>`/`<audio>` send no headers, so the
// URL carries a freshly refreshed token (authedUrl is the one sanctioned stamping point). The URL
// is rebuilt per (path, epoch): callers bump `epoch` on a retry so a stale token never survives a
// remount, and a build that failed retries itself until the connection exists.
export function useAuthedSrc(path: string | null, epoch = 0): string | null {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;
    setSrc(null);
    if (path === null) return;
    const build = () => {
      authedUrl(path)
        .then((url) => {
          // The gateway base URL is user-entered at connect time; media elements only ever get
          // http(s) URLs from here.
          const scheme = new URL(url).protocol;
          if (scheme !== "http:" && scheme !== "https:") return;
          if (!cancelled) setSrc(url);
        })
        .catch(() => {
          if (!cancelled) timer = window.setTimeout(build, REBUILD_RETRY_MS);
        });
    };
    build();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [path, epoch]);
  return src;
}
