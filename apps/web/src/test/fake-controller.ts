import { vi, type Mock } from "vitest";
import { createReplica, createSession } from "@vesta/core";
import type {
  AgentInfo,
  AgentNode,
  AgentRow,
  Controller,
  Delta,
  DeviceContext,
  GatewayInfo,
  NotificationEvent,
  SyncState,
  Tree,
} from "@vesta/core";

// Shared test fixtures for the provider suites: an inert Controller stub over a real replica, with a
// delta fan-out so a test can drive the provider through the same path /sync deltas take at runtime.

export function fakeGatewayInfo(
  overrides: Partial<GatewayInfo> = {},
): GatewayInfo {
  return {
    version: "0.2.0",
    channel: "stable",
    autoUpdate: true,
    port: 7777,
    lan: { exposed: false, url: null },
    tunnelUrl: null,
    updateAvailable: false,
    latestVersion: null,
    managed: false,
    operation: null,
    ...overrides,
  };
}

export function fakeAgentInfo(overrides: Partial<AgentInfo> = {}): AgentInfo {
  return {
    status: "alive",
    activityState: "idle",
    buildPhase: null,
    operation: null,
    startedAt: null,
    services: {},
    ...overrides,
  };
}

export function fakeAgentNode(
  overrides: Partial<AgentInfo> = {},
  pending: NotificationEvent[] = [],
): AgentNode {
  return { info: fakeAgentInfo(overrides), notifications: { pending } };
}

export function fakeAgentRow(
  name: string,
  overrides: Partial<AgentInfo> = {},
): AgentRow {
  return { name, ...fakeAgentInfo(overrides) };
}

export function fakeTree(overrides: Partial<Tree> = {}): Tree {
  return { gateway: fakeGatewayInfo(), agents: {}, devices: [], ...overrides };
}

export interface FakeController {
  controller: Controller;
  // Applies a delta to the replica and fans it out to the provider's delta subscribers.
  emit: (delta: Delta) => void;
  // Moves the sync sub-store and notifies its subscribers, as the live socket would.
  setSyncState: (next: SyncState) => void;
  // The stubbed http.json, so a test can inspect POST bodies or reject with an ApiError.
  json: Mock;
  // The stubbed http.request (the intents that read no body, e.g. the gateway restart).
  request: Mock;
  // What the provider reported upstream, in call order.
  reports: {
    presence: Mock<(focused: boolean) => void>;
    viewing: Mock<(agent: string | null) => void>;
    deviceContext: Mock<(context: DeviceContext) => void>;
  };
}

// `tree` null leaves the replica unsynced (the pre-snapshot state a fresh socket starts in).
export function fakeController(
  tree: Tree | null,
  opts: { anyFocused?: boolean; syncState?: SyncState } = {},
): FakeController {
  const replica = createReplica();
  if (tree) replica.applySnapshot(tree);
  const deltaListeners = new Set<(delta: Delta) => void>();
  const syncListeners = new Set<() => void>();
  let syncState: SyncState = opts.syncState ?? "open";
  const json = vi.fn().mockResolvedValue({});
  const request = vi.fn().mockResolvedValue(new Response(null));
  const reports = {
    presence: vi.fn<(focused: boolean) => void>(),
    viewing: vi.fn<(agent: string | null) => void>(),
    deviceContext: vi.fn<(context: DeviceContext) => void>(),
  };
  // A session over a fixed connection: its own http client is never dialed, the stubbed one is.
  const session = createSession({
    fetch: () => Promise.reject(new Error("fake session never fetches")),
    read: () => ({
      url: "https://vestad.test",
      accessToken: "tok",
      refreshToken: "ref",
      expiresAt: Number.MAX_SAFE_INTEGER,
    }),
    write: () => undefined,
  });
  const controller: Controller = {
    replica,
    http: { request, json },
    session,
    subscribeDeltas: (listener) => {
      deltaListeners.add(listener);
      return () => deltaListeners.delete(listener);
    },
    getSyncState: () => syncState,
    subscribeSyncState: (listener) => {
      syncListeners.add(listener);
      return () => syncListeners.delete(listener);
    },
    reportPresence: reports.presence,
    reportViewing: reports.viewing,
    reportDeviceContext: reports.deviceContext,
    getAnyFocused: () => opts.anyFocused ?? false,
    subscribeAnyFocused: () => () => undefined,
    close: () => undefined,
  };
  const emit = (delta: Delta): void => {
    replica.applyDelta(delta);
    for (const listener of deltaListeners) listener(delta);
  };
  const setSyncState = (next: SyncState): void => {
    syncState = next;
    for (const listener of syncListeners) listener();
  };
  return { controller, emit, setSyncState, json, request, reports };
}
