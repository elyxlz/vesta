import { useContext, useEffect } from "react";
import * as Notifications from "expo-notifications";
import type { Controller, Delta } from "@vesta/core";
import { useSyncState } from "@vesta/core/react";
import { ControllerContext } from "@/controller/context";
import { shouldPresentUserNotification } from "./user-notification-presentation";
import { setSyncConnected } from "./foreground-policy";

// The single owner of foreground notifications: it presents ONE local notification per server
// `user_notification` delta (defer-to-active applied), mirroring web's ReplicaNotifications. While it
// holds a connected socket the Expo-push handler suppresses its own presentation (foreground-policy),
// so there is no double-notify. Rendered only when a controller exists.
function LiveUserNotifications({ controller }: { controller: Controller }) {
  const connected = useSyncState(controller) === "open";

  useEffect(() => {
    setSyncConnected(connected);
    return () => setSyncConnected(false);
  }, [connected]);

  useEffect(() => {
    return controller.subscribeDeltas((delta: Delta) => {
      if (delta.type !== "user_notification") return;
      // The conversation this client reported it is reading, from the one owner of that fact:
      // the router feeds it through PresenceReporter, so a second mounted chat socket cannot
      // move it and a backgrounded app reports none.
      if (!shouldPresentUserNotification(delta, controller.getViewing()))
        return;
      void Notifications.scheduleNotificationAsync({
        content: { title: delta.title, body: delta.body },
        trigger: null,
      });
    });
  }, [controller]);

  return null;
}

export function UserNotifications() {
  const controller = useContext(ControllerContext);
  if (!controller) return null;
  return <LiveUserNotifications controller={controller} />;
}
