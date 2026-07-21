import { reduceDelta } from "./reducer"
import type { Delta } from "../protocol/deltas"
import type { Tree } from "../protocol/tree"

export interface Replica {
  getState: () => Tree | null
  subscribe: (listener: () => void) => () => void
  applySnapshot: (tree: Tree) => void
  applyDelta: (delta: Delta) => void
}

export function createReplica(): Replica {
  let state: Tree | null = null
  const listeners = new Set<() => void>()
  const emit = (): void => {
    for (const listener of listeners) listener()
  }
  return {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    applySnapshot: (tree) => {
      state = tree
      emit()
    },
    applyDelta: (delta) => {
      if (state === null) return
      const next = reduceDelta(state, delta)
      if (next === state) return
      state = next
      emit()
    },
  }
}
