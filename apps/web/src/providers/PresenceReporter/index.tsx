import { useContext, useEffect } from "react";
import { ControllerContext } from "@/providers/ControllerProvider";
import { useWindowFocus } from "@/hooks/use-window-focus";

export function PresenceReporter() {
  const controller = useContext(ControllerContext);
  const focused = useWindowFocus();

  useEffect(() => {
    if (!controller) return;
    controller.reportPresence(focused);
  }, [controller, focused]);

  return null;
}
