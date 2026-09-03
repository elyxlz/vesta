import { useEffect, useRef } from "react";
import { compareReleaseVersions } from "@vesta/core";
import { useGateway } from "@/providers/GatewayProvider/context";
import { usePreferences } from "@/stores/use-preferences";
import {
  fetchReleaseNotes,
  filterReleaseNotes,
  type ReleaseNote,
} from "@vesta/core";

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

    const { whatsNewLastSeen: lastSeen, update } = usePreferences.getState();
    if (lastSeen === null) {
      update({ whatsNewLastSeen: gatewayVersion });
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
        (entry) => compareReleaseVersions(entry.version, gatewayVersion) === 0,
      );
      if (!hasCurrent) return;
      update({ whatsNewLastSeen: gatewayVersion });
      onAutoOpen(visible);
    });
    return () => {
      cancelled = true;
    };
  }, [reachable, gatewayVersion, gatewayChannel, onAutoOpen]);
}
