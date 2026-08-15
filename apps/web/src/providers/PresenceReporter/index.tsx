import { useContext, useEffect, useState } from "react";
import { ControllerContext } from "@/providers/ControllerProvider";
import { useWindowFocus } from "@/hooks/use-window-focus";
import { router } from "@/router";

// The agent whose page is open, from the router's matched `agent/:name` param, or null off it. Read
// from the router directly because this reporter is mounted above the RouterProvider.
function currentAgent(): string | null {
  const match = router.state.matches.find((m) => m.params.name !== undefined);
  return match?.params.name ?? null;
}

export function PresenceReporter() {
  const controller = useContext(ControllerContext);
  const focused = useWindowFocus();
  const [agent, setAgent] = useState<string | null>(() => currentAgent());

  useEffect(() => {
    setAgent(currentAgent());
    return router.subscribe(() => {
      setAgent(currentAgent());
    });
  }, []);

  useEffect(() => {
    if (!controller) return;
    controller.reportPresence(focused);
  }, [controller, focused]);

  useEffect(() => {
    if (!controller) return;
    // Report the open agent only while focused; a blurred window is viewing no one.
    controller.reportViewing(focused ? agent : null);
  }, [controller, focused, agent]);

  return null;
}
