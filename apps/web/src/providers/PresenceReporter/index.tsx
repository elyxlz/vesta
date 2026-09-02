import { useContext, useEffect, useSyncExternalStore } from "react";
import { ControllerContext } from "@/providers/ControllerProvider/context";
import { useWindowFocus } from "@/hooks/use-window-focus";
import { readBrowserDeviceContext } from "@/lib/device-context";
import { useShareLocation } from "@/stores/use-share-location";
import { router } from "@/router";

// The agent whose page is open, from the router's matched `agent/:name` param, or null off it. Read
// from the router directly because this reporter is mounted above the RouterProvider.
function currentAgent(): string | null {
  const match = router.state.matches.find((m) => m.params.name !== undefined);
  return match?.params.name ?? null;
}

const subscribeToRouter = (onChange: () => void) => router.subscribe(onChange);

export function PresenceReporter() {
  const controller = useContext(ControllerContext);
  const focused = useWindowFocus();
  const shareLocation = useShareLocation((s) => s.enabled);
  const agent = useSyncExternalStore(subscribeToRouter, currentAgent);

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
    // Report the open agent only while focused; a blurred window is viewing no one.
    controller.reportViewing(focused ? agent : null);
  }, [controller, focused, agent]);

  return null;
}
