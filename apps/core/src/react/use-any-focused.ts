import { useSyncExternalStore } from "react";
import type { Controller } from "../controller/controller";

const subscribeNothing = (): (() => void) => () => undefined;
const unfocused = (): boolean => false;

// The global "any client focused" flag, broadcast by vestad. Used to suppress local notifications
// cross-device: while any client anywhere is focused, this client stays quiet. False with no
// controller.
export function useAnyFocused(controller: Controller | null): boolean {
  return useSyncExternalStore(
    controller?.subscribeAnyFocused ?? subscribeNothing,
    controller?.getAnyFocused ?? unfocused,
    controller?.getAnyFocused ?? unfocused,
  );
}
