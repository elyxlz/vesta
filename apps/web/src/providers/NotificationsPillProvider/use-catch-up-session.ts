import { useEffect, useRef, useState } from "react";
import { feedHasUnseen } from "@vesta/core";

// One catch-up session spans popover and dialog: the synced watermark is
// snapshotted when the first history surface opens (so the unseen/seen split
// holds still while it is on screen) and released when the last one closes,
// which is when `markSeen` tells the gateway the user caught up, and only if
// anything unseen was on offer. Returns the held snapshot, or null while no
// surface is open. The refs let the close effect read the live values without
// re-running on every delta.
export function useCatchUpSession(
  historyOpen: boolean,
  seenAt: number,
  lastAt: number | null,
  markSeen: () => void,
): number | null {
  const [seenSnapshot, setSeenSnapshot] = useState<number | null>(null);
  const watermarkRef = useRef({ seenAt, lastAt });
  useEffect(() => {
    watermarkRef.current = { seenAt, lastAt };
  }, [seenAt, lastAt]);
  const markSeenRef = useRef(markSeen);
  useEffect(() => {
    markSeenRef.current = markSeen;
  }, [markSeen]);
  const snapshotRef = useRef<number | null>(null);
  useEffect(() => {
    if (historyOpen) {
      if (snapshotRef.current === null) {
        snapshotRef.current = watermarkRef.current.seenAt;
        setSeenSnapshot(snapshotRef.current);
      }
      return;
    }
    // Both surfaces closed: the session ends. "see all" flips popover to
    // dialog inside one render, so historyOpen never blips false mid-handoff.
    const snapshot = snapshotRef.current;
    snapshotRef.current = null;
    setSeenSnapshot(null);
    if (
      snapshot !== null &&
      feedHasUnseen(watermarkRef.current.lastAt, snapshot)
    ) {
      markSeenRef.current();
    }
  }, [historyOpen]);
  return seenSnapshot;
}
