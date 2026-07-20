import { useSyncExternalStore } from "react"
import type { Controller } from "../controller/controller"
import type { SyncState } from "../transport/socket"

// The live connection state, re-rendered on every transition. Reads the controller's
// sync sub-store directly; no polling.
export function useSyncState(controller: Controller): SyncState {
  return useSyncExternalStore(
    controller.subscribeSyncState,
    controller.getSyncState,
    controller.getSyncState,
  )
}
