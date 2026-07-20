// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest"
import { act, cleanup, renderHook } from "@testing-library/react"

import { useSyncState } from "./use-watch"
import { createReplica } from "../replica/store"
import type { Controller } from "../controller/controller"
import type { SyncState } from "../transport/socket"

function fakeController(initial: SyncState = "connecting"): {
  controller: Controller
  setState: (state: SyncState) => void
} {
  const listeners = new Set<() => void>()
  let state = initial
  const controller: Controller = {
    replica: createReplica(),
    http: {
      request: () => Promise.reject(new Error("unused")),
      json: () => Promise.reject(new Error("unused")),
    },
    reauth: () => undefined,
    subscribeDeltas: () => () => undefined,
    getSyncState: () => state,
    subscribeSyncState: (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    close: () => undefined,
  }
  const setState = (next: SyncState): void => {
    state = next
    for (const listener of listeners) listener()
  }
  return { controller, setState }
}

afterEach(cleanup)

describe("useSyncState", () => {
  it("returns the current state and re-renders on transitions", () => {
    const { controller, setState } = fakeController("connecting")
    const { result } = renderHook(() => useSyncState(controller))
    expect(result.current).toBe("connecting")
    act(() => {
      setState("open")
    })
    expect(result.current).toBe("open")
    act(() => {
      setState("reconnecting")
    })
    expect(result.current).toBe("reconnecting")
  })
})
