import { useCallback, useRef, useSyncExternalStore } from "react"
import type { Replica } from "../replica/store"
import type { Tree } from "../protocol/tree"

// Subscribe to a slice of the replica. getSnapshot must return a stable value while the
// store is unchanged, so the selected value is memoized behind an equality check (default
// Object.is; pass a structural comparator for derived arrays/objects). Provider-less: the
// replica is passed in, not read from a React context.
export function useReplica<T>(
  replica: Replica,
  selector: (tree: Tree | null) => T,
  isEqual: (a: T, b: T) => boolean = Object.is,
): T {
  const memo = useRef<{ value: T } | null>(null)
  const getSnapshot = useCallback((): T => {
    const next = selector(replica.getState())
    if (memo.current !== null && isEqual(memo.current.value, next)) return memo.current.value
    memo.current = { value: next }
    return next
  }, [replica, selector, isEqual])
  return useSyncExternalStore(replica.subscribe, getSnapshot, getSnapshot)
}
