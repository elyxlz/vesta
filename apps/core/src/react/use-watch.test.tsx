// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, render, renderHook } from "@testing-library/react"

import { useSyncState, useWatch } from "./use-watch"
import { createReplica } from "../replica/store"
import type { ReactElement } from "react"
import type { Controller } from "../controller/controller"
import type { SyncState } from "../transport/socket"

function fakeController(initial: SyncState = "connecting"): {
  controller: Controller
  watch: ReturnType<typeof vi.fn>
  unwatch: ReturnType<typeof vi.fn>
  setState: (state: SyncState) => void
} {
  const watch = vi.fn()
  const unwatch = vi.fn()
  const listeners = new Set<() => void>()
  let state = initial
  const controller: Controller = {
    replica: createReplica(),
    http: {
      request: () => Promise.reject(new Error("unused")),
      json: () => Promise.reject(new Error("unused")),
    },
    watch,
    unwatch,
    reauth: vi.fn(),
    subscribeDeltas: () => () => undefined,
    getSyncState: () => state,
    subscribeSyncState: (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    close: vi.fn(),
  }
  const setState = (next: SyncState): void => {
    state = next
    for (const listener of listeners) listener()
  }
  return { controller, watch, unwatch, setState }
}

function Watcher({
  controller,
  agent,
}: {
  controller: Controller
  agent: string | null
}): ReactElement {
  useWatch(controller, agent)
  return <span />
}

afterEach(cleanup)

describe("useWatch", () => {
  it("watches on mount and unwatches on unmount", () => {
    const { controller, watch, unwatch } = fakeController()
    const { unmount } = render(<Watcher controller={controller} agent="scout" />)
    expect(watch.mock.calls).toEqual([["scout"]])
    unmount()
    expect(unwatch.mock.calls).toEqual([["scout"]])
  })

  it("re-watches when the agent changes", () => {
    const { controller, watch, unwatch } = fakeController()
    const { rerender } = render(<Watcher controller={controller} agent="scout" />)
    rerender(<Watcher controller={controller} agent="ranger" />)
    expect(watch.mock.calls).toEqual([["scout"], ["ranger"]])
    expect(unwatch.mock.calls).toEqual([["scout"]])
  })

  it("watches nothing for a null agent", () => {
    const { controller, watch, unwatch } = fakeController()
    render(<Watcher controller={controller} agent={null} />)
    expect(watch).not.toHaveBeenCalled()
    expect(unwatch).not.toHaveBeenCalled()
  })
})

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
