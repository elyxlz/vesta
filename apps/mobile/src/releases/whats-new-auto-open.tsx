import { useEffect, useRef, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useQuery } from "@tanstack/react-query";
import {
  compareReleaseVersions,
  filterReleaseNotes,
  type ReleaseChannel,
} from "@vesta/core";
import { usePathname, useRouter } from "expo-router";
import { useRoster } from "@/session/RosterProvider";
import { releaseNotesQueryOptions } from "./release-notes-query";

const LAST_SEEN_VERSION_KEY = "vesta.whats-new-last-seen.v1";

interface PendingVersion {
  version: string;
  channel: ReleaseChannel;
}

export function WhatsNewAutoOpen({ enabled }: { enabled: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const roster = useRoster();
  const checkedRef = useRef(false);
  const handledVersionRef = useRef<string | null>(null);
  const [pending, setPending] = useState<PendingVersion | null>(null);
  const notes = useQuery({
    ...releaseNotesQueryOptions(pending?.version),
    enabled: pending !== null,
    staleTime: 0,
  });

  useEffect(() => {
    if (
      checkedRef.current ||
      !enabled ||
      !roster.reachable ||
      !roster.gatewayVersion ||
      !roster.gatewayChannel
    ) {
      return;
    }
    checkedRef.current = true;
    let active = true;
    const current: PendingVersion = {
      version: roster.gatewayVersion,
      channel: roster.gatewayChannel,
    };

    void AsyncStorage.getItem(LAST_SEEN_VERSION_KEY)
      .then((lastSeen) => {
        if (!active) return;
        if (lastSeen === null) {
          return AsyncStorage.setItem(LAST_SEEN_VERSION_KEY, current.version);
        }
        if (lastSeen !== current.version) setPending(current);
      })
      .catch(() => undefined);

    return () => {
      active = false;
    };
  }, [enabled, roster.gatewayChannel, roster.gatewayVersion, roster.reachable]);

  useEffect(() => {
    if (!pending || !notes.data || notes.isFetching || notes.isError) return;
    if (handledVersionRef.current === pending.version) return;
    handledVersionRef.current = pending.version;
    const visible = filterReleaseNotes(notes.data, pending);
    const includesCurrentVersion = visible.some(
      (note) => compareReleaseVersions(note.version, pending.version) === 0,
    );
    if (!includesCurrentVersion) return;

    void AsyncStorage.setItem(LAST_SEEN_VERSION_KEY, pending.version).catch(
      () => undefined,
    );
    if (pathname !== "/whats-new") router.push("/whats-new");
  }, [notes.data, notes.isError, notes.isFetching, pathname, pending, router]);

  return null;
}
