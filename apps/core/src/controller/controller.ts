import { createReplica } from "../replica/store"
import { createSyncSocket } from "../transport/socket"
import { createHttpClient } from "../transport/http"
import type { Replica } from "../replica/store"
import type { SyncSocketDeps, SyncState } from "../transport/socket"
import type { HttpClient, HttpDeps } from "../transport/http"
import type { Delta } from "../protocol/deltas"

export interface ControllerDeps {
  sync: SyncSocketDeps
  http: HttpDeps
}

export interface Controller {
  replica: Replica
  http: HttpClient
  reauth: (token: string) => void
  // The server's always-on `user_notification` delta is not tree state, so the notification funnel
  // subscribes to it here. Every delta flows through; callers that want branch state read the replica instead.
  subscribeDeltas: (listener: (delta: Delta) => void) => () => void
  getSyncState: () => SyncState
  subscribeSyncState: (listener: () => void) => () => void
  reportPresence: (focused: boolean, activeAgent: string | null) => void
  getAnyFocused: () => boolean
  subscribeAnyFocused: (listener: () => void) => () => void
  close: () => void
}

// The single client-side orchestrator: one replica, one sync socket feeding it, one http
// client. Socket frames land in the replica (snapshot replace, delta reduce); connection
// state is its own tiny sub-store so views can render "reconnecting"/"app_behind"/"gateway_behind"
// without polling. Mobile constructs the same controller with its own adapters in Stage 6.
export function createController(deps: ControllerDeps): Controller {
  const replica = createReplica()
  const http = createHttpClient(deps.http)

  let syncState: SyncState = "connecting"
  const stateListeners = new Set<() => void>()
  const deltaListeners = new Set<(delta: Delta) => void>()
  const emitState = (): void => {
    for (const listener of stateListeners) listener()
  }

  let anyFocused = false
  const anyFocusedListeners = new Set<() => void>()
  const emitAnyFocused = (): void => {
    for (const listener of anyFocusedListeners) listener()
  }

  const socket = createSyncSocket(deps.sync, {
    onSnapshot: (tree) => {
      replica.applySnapshot(tree)
    },
    onDelta: (delta) => {
      replica.applyDelta(delta)
      for (const listener of deltaListeners) listener(delta)
      if (delta.type === "presence") {
        anyFocused = delta.anyFocused
        emitAnyFocused()
      }
    },
    onStateChange: (state) => {
      syncState = state
      emitState()
    },
  })

  return {
    replica,
    http,
    reauth: (token) => {
      socket.reauth(token)
    },
    subscribeDeltas: (listener) => {
      deltaListeners.add(listener)
      return () => {
        deltaListeners.delete(listener)
      }
    },
    getSyncState: () => syncState,
    subscribeSyncState: (listener) => {
      stateListeners.add(listener)
      return () => {
        stateListeners.delete(listener)
      }
    },
    reportPresence: (focused, activeAgent) => {
      socket.reportPresence(focused, activeAgent)
    },
    getAnyFocused: () => anyFocused,
    subscribeAnyFocused: (listener) => {
      anyFocusedListeners.add(listener)
      return () => {
        anyFocusedListeners.delete(listener)
      }
    },
    close: () => {
      socket.close()
    },
  }
}
