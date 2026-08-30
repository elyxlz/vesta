import { useEffect, useState } from "react";
import { authedUrl } from "@/lib/authed-url";

// A media element's src for a gateway path: `<img>`/`<video>`/`<audio>` send no headers, so the
// URL carries a freshly refreshed token (authedUrl is the one sanctioned stamping point). Rebuilt
// whenever the path changes; a mounted element keeps streaming on its already-opened connection.
export function useAuthedSrc(path: string | null): string | null {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setSrc(null);
    if (path === null) return;
    authedUrl(path)
      .then((url) => {
        if (!cancelled) setSrc(url);
      })
      .catch(() => {
        // Not connected yet: the element simply stays sourceless until a re-render.
      });
    return () => {
      cancelled = true;
    };
  }, [path]);
  return src;
}
