import { useSyncExternalStore } from "react";
import type { Controller } from "../controller/controller";

const subscribeNothing = (): (() => void) => () => undefined;
const unfocused = (): boolean => false;
const nobody = (): string | null => null;

// Whether this client's window is focused, as last reported to the controller. False with no
// controller.
export function useFocused(controller: Controller | null): boolean {
  return useSyncExternalStore(
    controller?.subscribeFocused ?? subscribeNothing,
    controller?.getFocused ?? unfocused,
    controller?.getFocused ?? unfocused,
  );
}

// The agent whose page is open on this client, as last reported to the controller; null on the
// roster or with no controller.
export function useViewing(controller: Controller | null): string | null {
  return useSyncExternalStore(
    controller?.subscribeViewing ?? subscribeNothing,
    controller?.getViewing ?? nobody,
    controller?.getViewing ?? nobody,
  );
}
