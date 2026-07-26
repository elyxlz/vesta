import { AppState, type AppStateStatus } from "react-native";
import type { ForegroundSignal } from "@vesta/core";

function keepsControllerAlive(state: AppStateStatus): boolean {
  // iOS enters `inactive` during transient system UI and an interrupted Home gesture. Waiting for
  // `background` avoids tearing the app down while it is still visibly returning to the foreground.
  return state === "active" || state === "inactive";
}

export function createAppStateForegroundSignal(): ForegroundSignal {
  const isForeground = () => keepsControllerAlive(AppState.currentState);
  return {
    isForeground,
    subscribe: (listener) => {
      const sub = AppState.addEventListener("change", (state: AppStateStatus) =>
        listener(keepsControllerAlive(state)),
      );
      return () => sub.remove();
    },
  };
}
