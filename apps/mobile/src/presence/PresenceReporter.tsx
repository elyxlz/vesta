import { useContext, useEffect, useState } from "react";
import { AppState, type AppStateStatus } from "react-native";
import { useGlobalSearchParams, useSegments } from "expo-router";
import { ControllerContext } from "@/controller/context";
import { registerBackgroundReport } from "@/device-context/background-report";
import { readDeviceContext } from "@/device-context/device-context";
import { requestLocationIfUndecided } from "@/device-context/location-consent";
import { usePreferences } from "@/preferences/PreferencesProvider";

function isFocused(state: AppStateStatus): boolean {
  return state === "active";
}

// Reports this device to vestad: app foreground (so it can suppress a push while a client is
// focused), the agent whose page is open (so it drops the per-agent presence notification), and the
// device context (zone, and position when shared) on each foreground edge, with the closed-app poll
// registered alongside. Reports the open agent only while foregrounded; a backgrounded app is
// viewing no one.
export function PresenceReporter() {
  const controller = useContext(ControllerContext);
  const { shareLocation } = usePreferences();
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

  // The closed-app poll reports the same context over HTTP; registering is idempotent.
  useEffect(() => {
    registerBackgroundReport().catch((cause: unknown) => {
      console.warn(
        "Could not register the background device context report:",
        cause,
      );
    });
  }, []);

  // On each foreground edge, read the phone's zone (and position, when shared) fresh and report it,
  // so a device that travelled reports as soon as the user opens the app. A shared read on a phone
  // the OS has never asked raises the location prompt first, which is what makes the default-on
  // preference share location out of the box.
  useEffect(() => {
    if (!controller || !active) return;
    let current = true;
    const read = async () => {
      if (shareLocation) await requestLocationIfUndecided();
      return readDeviceContext({ shareLocation, mode: "foreground" });
    };
    read()
      .then((context) => {
        if (current) controller.reportDeviceContext(context);
      })
      .catch((cause: unknown) => {
        console.warn("Could not read the device context:", cause);
      });
    return () => {
      current = false;
    };
  }, [controller, active, shareLocation]);

  return null;
}
