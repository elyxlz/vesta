import { AppState, type AppStateStatus } from "react-native";
import type { ForegroundSignal } from "@vesta/core";

export function createAppStateForegroundSignal(): ForegroundSignal {
  const isForeground = () => AppState.currentState === "active";
  return {
    isForeground,
    subscribe: (listener) => {
      const sub = AppState.addEventListener("change", (state: AppStateStatus) =>
        listener(state === "active"),
      );
      return () => sub.remove();
    },
  };
}
