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
  getAnyFocused: () => boolean;
  subscribeAnyFocused: (listener: () => void) => () => void;
  close: () => void;
}

// The single client-side orchestrator: one replica, one sync socket feeding it, the session's one
// http client, and the reauth tick that rotates the socket's token in-band before it expires.
// Socket frames land in the replica (snapshot replace, delta reduce); connection state is its own
// tiny sub-store so views can render "reconnecting"/"app_behind"/"gateway_behind" without polling.
// Mobile constructs the same controller with its own adapters.
export function createController(deps: ControllerDeps): Controller {
  const replica = createReplica();

  let syncState: SyncState = "connecting";
  const stateListeners = new Set<() => void>();
  const deltaListeners = new Set<(delta: Delta) => void>();
  const emitState = (): void => {
    for (const listener of stateListeners) listener();
  };

  let anyFocused = false;
  const anyFocusedListeners = new Set<() => void>();
  const emitAnyFocused = (): void => {
    for (const listener of anyFocusedListeners) listener();
  };

  const socket = createSyncSocket(
    { ...deps.sync, buildUrl: () => deps.session.websocketUrl("/sync") },
    {
      onSnapshot: (tree) => {
        replica.applySnapshot(tree);
      },
      onDelta: (delta) => {
        replica.applyDelta(delta);
        for (const listener of deltaListeners) listener(delta);
        if (delta.type === "presence") {
          anyFocused = delta.anyFocused;
          emitAnyFocused();
        }
      },
      onStateChange: (state) => {
        syncState = state;
        emitState();
      },
    },
  );

  // Also at once, not just every poll: a session restored with an already-expired token would
  // otherwise keep retrying /sync with it for a whole interval.
  let reauthTimer: number | null = null;
  let closed = false;
  const reauthTick = (): void => {
    void runReauthCheck(deps.session, (token) => {
      socket.reauth(token);
    }).then(() => {
      if (closed) return;
      reauthTimer = deps.sync.setTimer(reauthTick, REAUTH_POLL_MS);
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
    getSyncState: () => syncState,
    subscribeSyncState: (listener) => {
      stateListeners.add(listener);
      return () => {
        stateListeners.delete(listener);
      };
    },
    reportPresence: (focused) => {
      socket.reportPresence(focused);
    },
    reportViewing: (agent) => {
      socket.reportViewing(agent);
    },
    reportDeviceContext: (context) => {
      socket.reportDeviceContext(context);
    },
    getAnyFocused: () => anyFocused,
    subscribeAnyFocused: (listener) => {
      anyFocusedListeners.add(listener);
      return () => {
        anyFocusedListeners.delete(listener);
      };
    },
    close: () => {
      closed = true;
      if (reauthTimer !== null) deps.sync.clearTimer(reauthTimer);
      socket.close();
    },
  };
}
