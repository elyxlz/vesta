// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest"
import { act, cleanup, renderHook } from "@testing-library/react"
import { createKeyedHoldStore } from "../holds/keyed-hold"
import { useHeld } from "./use-held"

afterEach(cleanup)

describe("useHeld", () => {
  it("renders the held cell and follows later writes to the same key", () => {
    const hold = createKeyedHoldStore<string>()
    hold.persist("k", "one")
    const { result } = renderHook(() => useHeld(hold, "k"))
    expect(result.current).toBe("one")
    act(() => {
      hold.persist("k", "two")
    })
    expect(result.current).toBe("two")
  })

  it("reads null for a key never written and ignores writes to other keys", () => {
    const hold = createKeyedHoldStore<string>()
    const { result } = renderHook(() => useHeld(hold, "k"))
    expect(result.current).toBeNull()
    act(() => {
      hold.persist("other", "x")
    })
    expect(result.current).toBeNull()
  })
})
