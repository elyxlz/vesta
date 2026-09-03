import { useEffect, useSyncExternalStore } from "react";
import { useOptionalController } from "@/providers/ControllerProvider/context";
import { useWindowFocus } from "./use-window-focus";
import { readBrowserDeviceContext } from "@/lib/device-context";
import { usePreferences } from "@/stores/use-preferences";
import { router } from "@/router";

// The agent whose page is open, from the router's matched `agent/:name` param, or null off it. Read
// from the router directly because this reporter is mounted above the RouterProvider.
function currentAgent(): string | null {
  const match = router.state.matches.find((m) => m.params.name !== undefined);
  return match?.params.name ?? null;
}

const subscribeToRouter = (onChange: () => void) => router.subscribe(onChange);

// The single writer of this client's focus and viewed agent: the controller holds both facts for
// every consumer, and its socket masks the viewed agent to null on the wire while unfocused.
export function PresenceReporter() {
  const controller = useOptionalController();
  const focused = useWindowFocus();
  const shareLocation = usePreferences((s) => s.shareLocation);
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
    controller.reportViewing(agent);
  }, [controller, agent]);

  return null;
}
