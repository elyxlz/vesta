import { createReplica } from "../replica/store";
import { createSyncSocket } from "../transport/socket";
import {
  REAUTH_POLL_MS,
  runReauthCheck,
  type Session,
} from "../session/session";
import type { Replica } from "../replica/store";
import type { SyncSocketDeps, SyncState } from "../transport/socket";
import type { HttpClient } from "../transport/http";
import type { Delta } from "../protocol/deltas";
import type { DeviceContext } from "../protocol/frames";

export interface ControllerDeps {
  // The app's one gateway session: its http client is the controller's, and the sync socket
  // dials the session's own token-stamped URL.
  session: Session;
  sync: Omit<SyncSocketDeps, "buildUrl">;
}

export interface Controller {
  replica: Replica;
  http: HttpClient;
  session: Session;
  // The server's always-on `user_notification` delta is not tree state, so the notification funnel
  // subscribes to it here. Every delta flows through; callers that want branch state read the replica instead.
  subscribeDeltas: (listener: (delta: Delta) => void) => () => void;
  getSyncState: () => SyncState;
  subscribeSyncState: (listener: () => void) => () => void;
  reportPresence: (focused: boolean) => void;
  reportViewing: (agent: string | null) => void;
  reportDeviceContext: (context: DeviceContext) => void;
  // What this client last reported about itself: whether its window is focused, and the agent
  // whose page is open (null on the roster). One owner, so every consumer reads the same fact the
  // gateway was told; the socket masks viewing to null on the wire while unfocused.
  getFocused: () => boolean;
  subscribeFocused: (listener: () => void) => () => void;
  getViewing: () => string | null;
  subscribeViewing: (listener: () => void) => () => void;
  getAnyFocused: () => boolean;
  subscribeAnyFocused: (listener: () => void) => () => void;
  close: () => void;
}

function createCell<T>(initial: T): {
  get: () => T;
  set: (next: T) => void;
  subscribe: (listener: () => void) => () => void;
} {
  let value = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => value,
    set: (next) => {
      if (Object.is(value, next)) return;
      value = next;
      for (const listener of listeners) listener();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

// The single client-side orchestrator: one replica, one sync socket feeding it, the session's one
// http client, and the reauth tick that rotates the socket's token in-band before it expires.
// Socket frames land in the replica (snapshot replace, delta reduce); connection state is its own
// tiny sub-store so views can render "reconnecting"/"app_behind"/"gateway_behind" without polling.
// Mobile constructs the same controller with its own adapters.
export function createController(deps: ControllerDeps): Controller {
  const replica = createReplica();
  const syncState = createCell<SyncState>("connecting");
  const anyFocused = createCell(false);
  const focused = createCell(false);
  const viewing = createCell<string | null>(null);
  const deltaListeners = new Set<(delta: Delta) => void>();

  const socket = createSyncSocket(
    { ...deps.sync, buildUrl: () => deps.session.websocketUrl("/sync") },
    {
      onSnapshot: (tree) => {
        replica.applySnapshot(tree);
      },
      onDelta: (delta) => {
        replica.applyDelta(delta);
        for (const listener of deltaListeners) listener(delta);
        if (delta.type === "presence") anyFocused.set(delta.anyFocused);
      },
      onStateChange: syncState.set,
    },
  );

  // Also at once, not just every poll: a session restored with an already-expired token would
  // otherwise keep retrying /sync with it for a whole interval.
  let reauthTimer: ReturnType<typeof setTimeout> | null = null;
  let closed = false;
  const reauthTick = (): void => {
    void runReauthCheck(deps.session, (token) => {
      socket.reauth(token);
    }).then(() => {
      if (closed) return;
      reauthTimer = setTimeout(reauthTick, REAUTH_POLL_MS);
    });
  };
  reauthTick();

  return {
    replica,
    http: deps.session.http,
    session: deps.session,
    subscribeDeltas: (listener) => {
      deltaListeners.add(listener);
      return () => {
        deltaListeners.delete(listener);
      };
    },
    getSyncState: syncState.get,
    subscribeSyncState: syncState.subscribe,
    reportPresence: (next) => {
      focused.set(next);
      socket.reportPresence(next);
    },
    reportViewing: (agent) => {
      viewing.set(agent);
      socket.reportViewing(agent);
    },
    reportDeviceContext: (context) => {
      socket.reportDeviceContext(context);
    },
    getFocused: focused.get,
    subscribeFocused: focused.subscribe,
    getViewing: viewing.get,
    subscribeViewing: viewing.subscribe,
    getAnyFocused: anyFocused.get,
    subscribeAnyFocused: anyFocused.subscribe,
    close: () => {
      closed = true;
      if (reauthTimer !== null) clearTimeout(reauthTimer);
      socket.close();
    },
  };
}
