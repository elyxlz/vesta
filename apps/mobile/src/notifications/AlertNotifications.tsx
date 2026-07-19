import { useContext, useEffect } from "react";
import * as Notifications from "expo-notifications";
import type { Controller, Delta } from "@vesta/core";
import { useSyncState } from "@vesta/core/react";
import { ControllerContext } from "@/controller/context";
import { shouldPresentAlert } from "./alert-presentation";
import { activeAgentName, setSyncConnected } from "./foreground-policy";

// The single owner of foreground notifications: it presents ONE local notification per server
// `alert` delta (defer-to-active applied), mirroring web's ReplicaNotifications. While it holds
// a connected socket the Expo-push handler suppresses its own presentation (foreground-policy),
// so there is no double-notify. Rendered only when a controller exists.
function LiveAlertNotifications({ controller }: { controller: Controller }) {
  const connected = useSyncState(controller) === "open";

  useEffect(() => {
    setSyncConnected(connected);
    return () => setSyncConnected(false);
  }, [connected]);

  useEffect(() => {
    return controller.subscribeDeltas((delta: Delta) => {
      if (delta.type !== "alert") return;
      if (!shouldPresentAlert(delta, activeAgentName())) return;
      void Notifications.scheduleNotificationAsync({
        content: { title: delta.agent, body: delta.preview },
        trigger: null,
      });
    });
  }, [controller]);

  return null;
}

export function AlertNotifications() {
  const controller = useContext(ControllerContext);
  if (!controller) return null;
  return <LiveAlertNotifications controller={controller} />;
}
