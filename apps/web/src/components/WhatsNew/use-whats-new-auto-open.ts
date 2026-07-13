import { useEffect, useRef } from "react";
import { useGateway } from "@/providers/GatewayProvider";
import { compareVersions } from "@/lib/version";
import {
  fetchReleaseNotes,
  filterReleaseNotes,
  type ReleaseNote,
} from "@/lib/whats-new";

const LAST_SEEN_VERSION_KEY = "vesta:whats-new-last-seen";

/**
 * Open the dialog once after a vestad update: when the connected version
 * differs from the last one this browser saw and that version has a visible
 * release note. A fresh install just records the current version silently.
 * Checks at most once per app load; the fetched notes are handed to the
 * caller so opening does not refetch.
 */
export function useWhatsNewAutoOpen(
  onAutoOpen: (notes: ReleaseNote[]) => void,
) {
  const { reachable, gatewayVersion, gatewayChannel } = useGateway();
  const checkedRef = useRef(false);

  useEffect(() => {
    if (checkedRef.current || !reachable || !gatewayVersion) return;
    checkedRef.current = true;

    const lastSeen = localStorage.getItem(LAST_SEEN_VERSION_KEY);
    if (lastSeen === null) {
      localStorage.setItem(LAST_SEEN_VERSION_KEY, gatewayVersion);
      return;
    }
    if (lastSeen === gatewayVersion) return;

    let cancelled = false;
    void fetchReleaseNotes().then((fetched) => {
      if (cancelled || fetched === null) return;
      const visible = filterReleaseNotes(fetched, {
        version: gatewayVersion,
        channel: gatewayChannel,
      });
      const hasCurrent = visible.some(
        (entry) => compareVersions(entry.version, gatewayVersion) === 0,
      );
      if (!hasCurrent) return;
      localStorage.setItem(LAST_SEEN_VERSION_KEY, gatewayVersion);
      onAutoOpen(visible);
    });
    return () => {
      cancelled = true;
    };
  }, [reachable, gatewayVersion, gatewayChannel, onAutoOpen]);
}
