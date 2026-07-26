import { useCallback, useRef, useSyncExternalStore } from "react";
import type { Controller, SyncState, Tree } from "@vesta/core";

const subscribeEmpty = () => () => undefined;
const getClosedSyncState = (): SyncState => "closed";

// The core hook requires a live controller. This nullable variant keeps the calling component's
// hook order and identity stable while the controller is deliberately absent in the background.
export function useOptionalControllerReplica<T>(
  controller: Controller | null,
  selector: (tree: Tree | null) => T,
  isEqual: (a: T, b: T) => boolean = Object.is,
): T {
  const memo = useRef<{ value: T } | null>(null);
  const subscribe = useCallback(
    (listener: () => void) =>
      controller?.replica.subscribe(listener) ?? subscribeEmpty(),
    [controller],
  );
  const getSnapshot = useCallback((): T => {
    const next = selector(controller?.replica.getState() ?? null);
    if (memo.current !== null && isEqual(memo.current.value, next)) {
      return memo.current.value;
    }
    memo.current = { value: next };
    return next;
  }, [controller, selector, isEqual]);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function useOptionalControllerSyncState(
  controller: Controller | null,
): SyncState {
  return useSyncExternalStore(
    controller?.subscribeSyncState ?? subscribeEmpty,
    controller?.getSyncState ?? getClosedSyncState,
    controller?.getSyncState ?? getClosedSyncState,
  );
}
