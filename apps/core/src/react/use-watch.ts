import { useEffect, useSyncExternalStore } from "react"
import type { Controller } from "../controller/controller"
import type { SyncState } from "../transport/socket"

// Watch an agent's live edge for the lifetime of the mount. A null agent watches nothing.
// unwatch on cleanup / agent change is safe even after an agent_removed already cancelled it
// server-side (unwatch of an unwatched agent is a no-op).
export function useWatch(controller: Controller, agent: string | null): void {
  useEffect(() => {
    if (agent === null) return
    controller.watch(agent)
    return () => {
      controller.unwatch(agent)
    }
  }, [controller, agent])
}

// The live connection state, re-rendered on every transition. Reads the controller's
// sync sub-store directly; no polling.
export function useSyncState(controller: Controller): SyncState {
  return useSyncExternalStore(
    controller.subscribeSyncState,
    controller.getSyncState,
    controller.getSyncState,
  )
}
