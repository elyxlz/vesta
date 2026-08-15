import { useContext, useEffect, useState } from "react";
import { AppState, type AppStateStatus } from "react-native";
import { useGlobalSearchParams, useSegments } from "expo-router";
import { ControllerContext } from "@/controller/context";

function isFocused(state: AppStateStatus): boolean {
  return state === "active";
}

// Reports app foreground to vestad (so it can suppress a push while a client is focused) and the
// agent whose page is open (so it drops the per-agent presence notification). Reports the open agent
// only while foregrounded; a backgrounded app is viewing no one.
export function PresenceReporter() {
  const controller = useContext(ControllerContext);
  const segments = useSegments();
  const { name } = useGlobalSearchParams<{ name?: string }>();
  const agent = segments[0] === "agent" && name !== undefined ? name : null;
  const [active, setActive] = useState(() => isFocused(AppState.currentState));

  useEffect(() => {
    if (!controller) return;
    const report = (state: AppStateStatus) => {
      setActive(isFocused(state));
      controller.reportPresence(isFocused(state));
    };
    report(AppState.currentState);
    const sub = AppState.addEventListener("change", report);
    return () => sub.remove();
  }, [controller]);

  useEffect(() => {
    if (!controller) return;
    controller.reportViewing(active ? agent : null);
  }, [controller, active, agent]);

  return null;
}
