import { useEffect, useState } from "react";
import type { ApiClient } from "@/api/client";

// How long to wait before re-attempting a URL build that failed (not connected yet, refresh
// hiccup): cheap, bounded per mounted element, and self-healing without any caller wiring.
const REBUILD_RETRY_MS = 3000;

// A media element's uri for a gateway path: expo-image and expo-video send no auth headers, so
// the URL carries a freshly refreshed token (authedUrl is the one sanctioned stamping point).
// The URL is rebuilt per (path, epoch): callers bump `epoch` on a retry so a stale token never
// survives a remount, and a build that failed retries itself until the connection exists. The
// built uri is keyed by what it was built for, so a path or epoch change reads null (never a
// stale uri) without an in-effect reset.
export function useAuthedMediaUri(
  api: ApiClient,
  path: string | null,
  epoch = 0,
): string | null {
  const [built, setBuilt] = useState<{ key: string; uri: string } | null>(null);
  const key = `${path ?? ""}#${String(epoch)}`;
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    if (path === null) return;
    const build = () => {
      api
        .authedUrl(path)
        .then((url) => {
          // The gateway base URL is user-entered at connect time; media elements only ever get
          // http(s) URLs, re-serialized through the URL parser.
          const parsed = new URL(url);
          if (parsed.protocol !== "http:" && parsed.protocol !== "https:")
            return;
          if (!cancelled) setBuilt({ key, uri: parsed.href });
        })
        .catch(() => {
          if (!cancelled) timer = setTimeout(build, REBUILD_RETRY_MS);
        });
    };
    build();
    return () => {
      cancelled = true;
      if (timer !== null) clearTimeout(timer);
    };
  }, [api, path, key]);
  return path !== null && built?.key === key ? built.uri : null;
}
