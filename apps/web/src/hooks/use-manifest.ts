import { useEffect, useState } from "react";
import { fetchManifest, type Manifest } from "@/api/manifest";

// Fetches the provider manifest (catalog + new-agent defaults, served at GET /manifest) so the wizard
// and settings never keep their own copy. `undefined` until the one-shot fetch resolves; consumers
// render a loading state until then rather than falling back to a duplicated local default.
export function useManifest(): Manifest | undefined {
  const [manifest, setManifest] = useState<Manifest | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    fetchManifest()
      .then((m) => {
        if (!cancelled) setManifest(m);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return manifest;
}
