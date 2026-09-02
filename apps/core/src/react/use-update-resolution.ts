import { useEffect, useState } from "react";
import type { GatewayOperation } from "../protocol/tree";

// How long the "updated to vX.Y.Z" resolution stays up before the app returns to normal.
export const UPDATED_NOTICE_MS = 3000;
// A restart has less to say, so its landing is brief.
export const RESTARTED_NOTICE_MS = 2500;

interface UpdateWatch {
  active: boolean;
  // The version the watched operation started from; empty while none is known.
  before: string;
  updatedTo: string | null;
}

// Resolve the update the user watched: remember the version it started from, and once the operation
// clears against a different one, report it for a moment. The transition is derived in render from
// the operation's presence; only the notice's expiry is an Effect. A restart lands on the same
// version, so it resolves to nothing, which is exactly right. Every platform that renders the
// operation renders this too, which is what makes the gateway's own `gateway_updated` notification
// the unwatched case alone.
export function useUpdateResolution(
  operation: GatewayOperation | null,
  version: string,
): string | null {
  const active = operation !== null;
  const [watch, setWatch] = useState<UpdateWatch>({
    active,
    before: active ? version : "",
    updatedTo: null,
  });
  if (active !== watch.active) {
    // A new operation supersedes a still-showing notice. The empty version is "no gateway branch
    // yet", which resolves nothing either way.
    const landed =
      watch.before !== "" && version !== "" && watch.before !== version;
    setWatch({
      active,
      before: active ? version : "",
      updatedTo: !active && landed ? version : null,
    });
  } else if (active && watch.before === "" && version !== "") {
    setWatch({ ...watch, before: version });
  }
  useEffect(() => {
    if (watch.updatedTo === null) return;
    const clear = setTimeout(() => {
      setWatch((current) => ({ ...current, updatedTo: null }));
    }, UPDATED_NOTICE_MS);
    return () => {
      clearTimeout(clear);
    };
  }, [watch.updatedTo]);
  return watch.updatedTo;
}

interface RestartWatch {
  active: boolean;
  // Whether the active operation is a restart that has not failed.
  watching: boolean;
  restarted: boolean;
}

// Resolve the restart the user watched: once a restart operation clears without failing, report it
// for the same moment. A restart changes no version, so this is the only way it gets a landing.
export function useRestartResolution(
  operation: GatewayOperation | null,
): boolean {
  const active = operation !== null;
  const watching =
    operation !== null &&
    operation.kind === "restart" &&
    operation.phase !== "failed";
  const [watch, setWatch] = useState<RestartWatch>({
    active,
    watching,
    restarted: false,
  });
  if (active !== watch.active) {
    setWatch({ active, watching, restarted: !active && watch.watching });
  } else if (active && watching !== watch.watching) {
    setWatch({ active, watching, restarted: false });
  }
  useEffect(() => {
    if (!watch.restarted) return;
    const clear = setTimeout(() => {
      setWatch((current) => ({ ...current, restarted: false }));
    }, RESTARTED_NOTICE_MS);
    return () => {
      clearTimeout(clear);
    };
  }, [watch.restarted]);
  return watch.restarted;
}
