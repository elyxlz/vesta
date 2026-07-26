import { useContext, useEffect, useSyncExternalStore } from "react";
import { ControllerContext } from "@/providers/ControllerProvider";
import { useWindowFocus } from "@/hooks/use-window-focus";
import { router } from "@/router";

// The active agent is the one whose chat is open: the `/agent/:name` route param, the same value
// AgentSocketProvider pushes into NotificationProvider as the chatting agent. Read straight off the
// router singleton so presence reports from App level (above RouterProvider), on every route.
function activeAgentName(): string | null {
  for (const match of router.state.matches) {
    const name = match.params.name;
    if (name) return name;
  }
  return null;
}

function useActiveAgent(): string | null {
  return useSyncExternalStore(
    (onChange) => router.subscribe(onChange),
    activeAgentName,
  );
}

export function PresenceReporter() {
  const controller = useContext(ControllerContext);
  const focused = useWindowFocus();
  const activeAgent = useActiveAgent();

  useEffect(() => {
    if (!controller) return;
    controller.reportPresence(focused, activeAgent);
  }, [controller, focused, activeAgent]);

  return null;
}
