import { useContext, useEffect } from "react";
import { AppState, type AppStateStatus } from "react-native";
import { ControllerContext } from "@/controller/context";
import { activeAgentName } from "@/notifications/foreground-policy";

function isFocused(state: AppStateStatus): boolean {
  return state === "active";
}

// Reports app foreground + the visible agent to vestad so the gateway can suppress a push while a
// client is focused. Reports on mount and on every AppState transition (foreground/background), which
// is exactly when suppression flips; activeAgentName() is re-read on each change.
export function PresenceReporter() {
  const controller = useContext(ControllerContext);
  useEffect(() => {
    if (!controller) return;
    const report = (state: AppStateStatus) =>
      controller.reportPresence(isFocused(state), activeAgentName());
    report(AppState.currentState);
    const sub = AppState.addEventListener("change", report);
    return () => sub.remove();
  }, [controller]);
  return null;
}
