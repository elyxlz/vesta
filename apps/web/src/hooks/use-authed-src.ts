import { useResource } from "@vesta/core/react";
import { authedUrl } from "@/api/client";

// How long to wait before re-attempting a URL build that failed (not connected yet, refresh
// hiccup): cheap, bounded per mounted element, and self-healing without any caller wiring.
const REBUILD_RETRY_MS = 3000;

// A media element's src for a gateway path: `<img>`/`<video>`/`<audio>` send no headers, so the
// URL carries a freshly refreshed token (authedUrl is the one sanctioned stamping point). The URL
// is rebuilt per (path, epoch): callers bump `epoch` on a retry so a stale token never survives a
// remount, and a build that failed retries itself until the connection exists.
export function useAuthedSrc(path: string | null, epoch = 0): string | null {
  const key = path === null ? null : `${String(epoch)} ${path}`;
  const src = useResource(
    key,
    async () => {
      if (path === null) return null;
      const url = await authedUrl(path);
      // The gateway base URL is user-entered at connect time; media elements only ever get
      // http(s) URLs, re-serialized through the URL parser.
      const parsed = new URL(url);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:")
        return null;
      return parsed.href;
    },
    { retryMs: REBUILD_RETRY_MS },
  );
  return src.data;
}
