import { vi } from "vitest";
import { createReplica } from "@vesta/core";
import type { Controller, Delta, GatewayInfo, Tree } from "@vesta/core";

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

export function fakeTree(overrides: Partial<Tree> = {}): Tree {
  return { gateway: fakeGatewayInfo(), agents: {}, devices: [], ...overrides };
}

export interface FakeController {
  controller: Controller;
  // Applies a delta to the replica and fans it out to the provider's delta subscribers.
  emit: (delta: Delta) => void;
  // The stubbed http.json, so a test can inspect POST bodies or reject with an ApiError.
  json: ReturnType<typeof vi.fn>;
}

export function fakeController(
  tree: Tree,
  opts: { anyFocused?: boolean } = {},
): FakeController {
  const replica = createReplica();
  replica.applySnapshot(tree);
  const listeners = new Set<(delta: Delta) => void>();
  const json = vi.fn().mockResolvedValue({});
  const controller: Controller = {
    replica,
    http: { request: vi.fn(), json },
    reauth: vi.fn(),
    subscribeDeltas: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSyncState: () => "open",
    subscribeSyncState: () => () => undefined,
    reportPresence: () => undefined,
    reportViewing: () => undefined,
    reportDeviceContext: () => undefined,
    getAnyFocused: () => opts.anyFocused ?? false,
    subscribeAnyFocused: () => () => undefined,
    close: () => undefined,
  };
  const emit = (delta: Delta): void => {
    replica.applyDelta(delta);
    for (const listener of listeners) listener(delta);
  };
  return { controller, emit, json };
}
