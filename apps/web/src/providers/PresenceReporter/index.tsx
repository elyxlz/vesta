import { useEffect, useSyncExternalStore } from "react";
import { useOptionalController } from "@/providers/ControllerProvider/context";
import { currentRoom } from "./current-room";
import { useWindowFocus } from "./use-window-focus";
import { readBrowserDeviceContext } from "@/lib/device-context";
import { usePreferences } from "@/stores/use-preferences";
import { router } from "@/router";

// Read from the router directly because this reporter is mounted above the RouterProvider.
function routedRoom(): string | null {
  return currentRoom(router.state.matches.map((match) => match.params));
}

const subscribeToRouter = (onChange: () => void) => router.subscribe(onChange);

// The single writer of this client's focus and viewed room: the controller holds both facts for
// every consumer, and its socket masks the viewed room to null on the wire while unfocused.
export function PresenceReporter() {
  const controller = useOptionalController();
  const focused = useWindowFocus();
  const shareLocation = usePreferences((s) => s.shareLocation);
  const room = useSyncExternalStore(subscribeToRouter, routedRoom);

  useEffect(() => {
    if (!controller) return;
    controller.reportPresence(focused);
  }, [controller, focused]);

  useEffect(() => {
    if (!controller || !focused) return;
    // Read on each focus edge (and when the location opt-in changes), so a device that changed zone
    // or turned sharing on or off reports it as soon as the user is back.
    let cancelled = false;
    void readBrowserDeviceContext(shareLocation).then((context) => {
      if (!cancelled) controller.reportDeviceContext(context);
    });
    return () => {
      cancelled = true;
    };
  }, [controller, focused, shareLocation]);

  useEffect(() => {
    if (!controller) return;
    controller.reportViewing(room);
  }, [controller, room]);

  return null;
}
