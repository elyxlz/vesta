import { useCallback } from "react";
import type { Tree } from "@vesta/core";
import { useReplica } from "@vesta/core/react";
import { useController } from "@/providers/ControllerProvider/context";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";

function idsEqual(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((value, i) => value === b[i]);
}

// The ids of the notifications still on the agent's disk, unprocessed. It is an agent fact, so it
// rides the replica: the /sync tree carries the pending set and re-sends it on every change, which
// keeps the card's pending marks live with no polling.
export function usePendingNotifications(): string[] {
  const { name } = useSelectedAgent();
  const controller = useController();

  const pendingSelector = useCallback(
    (tree: Tree | null): string[] =>
      (tree?.agents[name]?.notifications.pending ?? []).flatMap((notif) =>
        notif.notif_id ? [notif.notif_id] : [],
      ),
    [name],
  );
  return useReplica(controller.replica, pendingSelector, idsEqual);
}
