import { useSyncExternalStore } from "react"
import type { Controller } from "../controller/controller"

// The global "any client focused" flag, broadcast by vestad. Used to suppress local notifications
// cross-device: while any client anywhere is focused, this client stays quiet.
export function useAnyFocused(controller: Controller): boolean {
  return useSyncExternalStore(
    controller.subscribeAnyFocused,
    controller.getAnyFocused,
    controller.getAnyFocused,
  )
}
