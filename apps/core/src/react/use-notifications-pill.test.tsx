// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, renderHook } from "@testing-library/react"

import { useNotificationsPill, type PillDeltaSource } from "./use-notifications-pill"
import { PILL_SHOW_MS } from "../notifications-pill/notifications-pill"
import type { Delta } from "../protocol/deltas"

function fakeSource(): PillDeltaSource & { emit: (delta: Delta) => void } {
  const listeners = new Set<(delta: Delta) => void>()
  return {
    subscribeDeltas: (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    emit: (delta) => {
      for (const listener of listeners) listener(delta)
    },
  }
}

function message(id: number, agent = "aria"): Delta {
  return {
    type: "user_notification",
    id,
    at: id * 100,
    agent,
    kind: "message",
    title: agent,
    body: "hi",
  }
}

function mount(source: PillDeltaSource, viewedAgent: string | null = null, paused = false) {
  return renderHook(() =>
    useNotificationsPill(source, { viewedAgent, orbStateFor: () => null, paused }),
  )
}

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe("useNotificationsPill", () => {
  it("shows arrivals one at a time under the log's own id and advances on the timer", () => {
    const source = fakeSource()
    const { result } = mount(source)
    act(() => {
      source.emit(message(7))
      source.emit(message(8))
    })
    expect(result.current.current?.id).toBe(7)
    act(() => {
      vi.advanceTimersByTime(PILL_SHOW_MS)
    })
    expect(result.current.current?.id).toBe(8)
    act(() => {
      vi.advanceTimersByTime(PILL_SHOW_MS)
    })
    expect(result.current.current).toBeNull()
  })

  it("drops exactly the shown item when a dismiss races the advance timer", () => {
    const source = fakeSource()
    const { result } = mount(source)
    act(() => {
      source.emit(message(7))
      source.emit(message(8))
    })
    act(() => {
      vi.advanceTimersByTime(PILL_SHOW_MS)
      result.current.dismiss()
    })
    expect(result.current.current?.id).toBe(8)
  })

  it("hides the viewed agent's own message and skips the queue while paused", () => {
    const source = fakeSource()
    const viewing = mount(source, "aria")
    act(() => {
      source.emit(message(1, "aria"))
      source.emit(message(2, "apollo"))
    })
    expect(viewing.result.current.current?.id).toBe(2)

    const paused = mount(source, null, true)
    act(() => {
      source.emit(message(3))
    })
    expect(paused.result.current.current).toBeNull()
  })
})
