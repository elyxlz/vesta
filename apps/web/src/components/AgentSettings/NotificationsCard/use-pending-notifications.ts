import { useCallback } from "react";
import {
  samePendingNotifications,
  type NotificationEvent,
  type Tree,
} from "@vesta/core";
import { useReplica } from "@vesta/core/react";
import { useController } from "@/providers/ControllerProvider/context";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";

// The notifications still on the agent's disk, unprocessed. It is an agent fact, so it rides the
// replica: the /sync tree carries the pending set as whole events and re-sends it on every change,
// which keeps the card's rows and their pending marks live with no polling.
export function usePendingNotifications(): NotificationEvent[] {
  const { name } = useSelectedAgent();
  const controller = useController();

  const pendingSelector = useCallback(
    (tree: Tree | null): NotificationEvent[] =>
      tree?.agents[name]?.notifications.pending ?? [],
    [name],
  );
  return useReplica(
    controller.replica,
    pendingSelector,
    samePendingNotifications,
  );
}
