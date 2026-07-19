import { describe, expect, it } from "vitest"

import {
  ApiError,
  createHttpClient,
  createReplica,
  createSendMessageIntent,
  createSyncSocket,
  createWatchManager,
  encodeFrame,
  parseServerFrame,
  PROTOCOL_FLOOR,
  PROTOCOL_VERSION,
  readSse,
  reauthFrame,
  reduceDelta,
  unwatchFrame,
  watchFrame,
} from "./index"
import type { StorageAdapter, SyncState, Tree } from "./index"

describe("@vesta/core barrel", () => {
  it("re-exports the runtime surface later stages import", () => {
    const runtime = [
      createHttpClient,
      createReplica,
      createSendMessageIntent,
      createSyncSocket,
      createWatchManager,
      encodeFrame,
      parseServerFrame,
      readSse,
      reauthFrame,
      reduceDelta,
      unwatchFrame,
      watchFrame,
    ]
    for (const value of runtime) expect(value).toBeTypeOf("function")
    expect(ApiError).toBeTypeOf("function")
    expect(PROTOCOL_VERSION).toBe(1)
    expect(PROTOCOL_FLOOR).toBe(1)
  })

  it("re-exports the type surface", () => {
    const state: SyncState = "open"
    const storage: StorageAdapter = {
      get: () => Promise.resolve(null),
      set: () => Promise.resolve(),
      remove: () => Promise.resolve(),
    }
    const tree: Tree | null = null
    expect(state).toBe("open")
    expect(tree).toBeNull()
    expect(storage.get).toBeTypeOf("function")
  })
})
