import { describe, expect, it, vi } from "vitest";

// The shipped package is untranspiled RN code node cannot parse; the factory under test takes
// the module shape injected anyway.
vi.mock("@react-native-community/netinfo", () => ({
  default: { addEventListener: () => () => undefined },
}));

import { createNetInfoConnectivity } from "./connectivity";

function fakeNet() {
  const listeners = new Set<(state: { isConnected: boolean | null }) => void>();
  return {
    addEventListener: (
      listener: (state: { isConnected: boolean | null }) => void,
    ) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    emit: (isConnected: boolean | null) => {
      for (const listener of [...listeners]) listener({ isConnected });
    },
  };
}

describe("netinfo connectivity", () => {
  it("caches the latest answer and fires subscribers on the edge only", () => {
    const net = fakeNet();
    const connectivity = createNetInfoConnectivity(net);
    expect(connectivity.isOnline()).toBe(true);

    const edges: boolean[] = [];
    const unsubscribe = connectivity.onChange((online) => edges.push(online));

    net.emit(false);
    expect(connectivity.isOnline()).toBe(false);
    net.emit(false); // no repeat edge
    net.emit(true);
    expect(connectivity.isOnline()).toBe(true);
    expect(edges).toEqual([false, true]);

    unsubscribe();
    net.emit(false);
    expect(edges).toEqual([false, true]);
    expect(connectivity.isOnline()).toBe(false);
  });

  it("treats an unknown answer as online", () => {
    const net = fakeNet();
    const connectivity = createNetInfoConnectivity(net);
    net.emit(false);
    net.emit(null);
    expect(connectivity.isOnline()).toBe(true);
  });
});
