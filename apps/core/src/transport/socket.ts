import {
  clientContextFrame,
  encodeFrame,
  reauthFrame,
} from "../protocol/frames";
import type {
  ClientFrame,
  ClientKind,
  DeviceContext,
  HelloFrame,
} from "../protocol/frames";
import { parseServerFrame } from "../protocol/parse";
import {
  clientAheadOfGateway,
  clientBelowMinimum,
} from "../protocol/release-version";
import type { Delta } from "../protocol/deltas";
import type { Tree } from "../protocol/tree";
import {
  createReconnectingSocket,
  type ReconnectingSocketDeps,
} from "./reconnecting-socket";

// The hello's served window (min_supported <= client <= version) drives two blocked states.
// "app_behind" is terminal for the session: the client is older than the gateway's minimum, so
// only the app updating resolves it (no retry storm). "gateway_behind" is recoverable: the
// client is newer than the gateway, so the socket stays live and re-hellos into "open" once the
// gateway restarts newer.
export type SyncState =
  | "connecting"
  | "open"
  | "reconnecting"
  | "app_behind"
  | "gateway_behind"
  | "closed";

export interface SyncSocketDeps extends ReconnectingSocketDeps {
  // This client's own release version, used to block running ahead of the gateway. Omitted (or
  // unparseable) fails open, so a dev build with a non-semver version never blocks.
  clientVersion?: string;
  clientKind: ClientKind;
  // This device's stable installation id and self-composed label, reported so vestad tracks it in
  // the device registry. Omitted by a build that has no identity to report; then it is untracked.
  device?: { id: string; descriptor: string };
}

export interface SyncSocketCallbacks {
  onSnapshot: (tree: Tree) => void;
  onDelta: (delta: Delta) => void;
  onStateChange: (state: SyncState) => void;
}

export interface SyncSocket {
  reauth: (token: string) => void;
  reportPresence: (focused: boolean) => void;
  reportViewing: (agent: string | null) => void;
  // What this device reports about itself (zone, position). Cached like focus and viewing, so the
  // reconnect replay carries the latest report; the caller decides when to read the device.
  reportDeviceContext: (context: DeviceContext) => void;
  close: () => void;
}

export function createSyncSocket(
  deps: SyncSocketDeps,
  callbacks: SyncSocketCallbacks,
): SyncSocket {
  let lastFocused: boolean | null = null;
  // The agent whose page is open on this client, null on the roster or before any report. The
  // wire carries it only while focused: a blurred window is viewing no one.
  let lastViewing: string | null = null;
  let lastContext: DeviceContext | undefined;
  // Whether the gateway already has the latest reported context (focus + viewing). False while a
  // report is still undelivered, so its replay goes out as the fresh context it is, not a resync.
  let contextSynced = false;
  // A token whose reauth was issued before the socket opened, held for that open. The gateway arms
  // the session deadline from the connect token and only a reauth extends it, so dropping the frame
  // would strand a live socket on a token that is about to expire.
  let pendingToken: string | null = null;
  // Set when the hello retires the socket for good, so the final phase reads as app_behind.
  let appBehind = false;

  // The current focus + viewing context as one frame. `lastFocused ?? false` covers a client that
  // reported a viewed page before any presence frame; in practice presence is reported on mount.
  const contextFrame = (resync: boolean): ClientFrame =>
    clientContextFrame({
      focused: lastFocused ?? false,
      client: deps.clientKind,
      resync,
      viewing: lastFocused ? lastViewing : null,
      device: deps.device,
      context: lastContext,
    });

  // Compare this client's own build version to the hello's served window. Fails open when the
  // client version is unknown (dev builds), and app_behind (terminal) wins over gateway_behind.
  const classifyHello = (hello: HelloFrame): SyncState | null => {
    const client = deps.clientVersion;
    if (client === undefined) return null;
    if (clientBelowMinimum(client, hello.minSupported)) return "app_behind";
    if (clientAheadOfGateway(client, hello.version)) return "gateway_behind";
    return null;
  };

  const socket = createReconnectingSocket(deps, {
    onOpen: (live) => {
      if (pendingToken !== null) {
        live.send(encodeFrame(reauthFrame(pendingToken)));
        pendingToken = null;
      }
      // Replay cached context. Already delivered means this is a reconnect, so it goes out as a
      // resync and vestad doesn't read it as the user returning; never delivered (the report was
      // issued while the socket was still connecting) means this is that first genuine context.
      if (lastFocused !== null || lastViewing !== null) {
        live.send(encodeFrame(contextFrame(contextSynced)));
        contextSynced = true;
      }
    },
    onMessage: (data) => {
      const parsed = parseServerFrame(data);
      switch (parsed.kind) {
        case "hello": {
          const outcome = classifyHello(parsed.frame);
          if (outcome === "app_behind") {
            appBehind = true;
            socket.close();
          } else if (outcome === "gateway_behind")
            callbacks.onStateChange("gateway_behind");
          return;
        }
        case "snapshot":
          callbacks.onSnapshot(parsed.frame.tree);
          return;
        case "delta":
          callbacks.onDelta(parsed.delta);
          return;
        case "unknown":
          return;
      }
    },
    onPhaseChange: (phase) => {
      callbacks.onStateChange(
        phase === "closed" && appBehind ? "app_behind" : phase,
      );
    },
  });

  // Both client frames are last-write-wins, so an undelivered one is re-issued from its cached
  // value on open; a genuine user-driven report (resync=false) may fire the presence notification.
  const emitContext = (): void => {
    contextSynced = socket.send(encodeFrame(contextFrame(false)));
  };

  return {
    reauth: (token) => {
      if (!socket.send(encodeFrame(reauthFrame(token)))) pendingToken = token;
    },
    reportPresence: (focused) => {
      // Skip repeated AppState/window-focus reports; the cached value still drives reconnect replay.
      if (lastFocused === focused) return;
      lastFocused = focused;
      emitContext();
    },
    reportViewing: (agent) => {
      // Skip repeated route reports; the cached value still drives reconnect replay.
      if (lastViewing === agent) return;
      lastViewing = agent;
      emitContext();
    },
    reportDeviceContext: (context) => {
      // Skip a report identical to the last; the cached value still drives reconnect replay.
      if (JSON.stringify(context) === JSON.stringify(lastContext)) return;
      lastContext = context;
      emitContext();
    },
    close: () => {
      pendingToken = null;
      socket.close();
    },
  };
}
