import { useSyncExternalStore } from "react";
import type { Controller } from "../controller/controller";
import type { SyncState } from "../transport/socket";

const subscribeNothing = (): (() => void) => () => undefined;
const closedState = (): SyncState => "closed";

// The live connection state, re-rendered on every transition. Reads the controller's
// sync sub-store directly; no polling. With no controller the state is "closed".
export function useSyncState(controller: Controller | null): SyncState {
  return useSyncExternalStore(
    controller?.subscribeSyncState ?? subscribeNothing,
    controller?.getSyncState ?? closedState,
    controller?.getSyncState ?? closedState,
  );
}
