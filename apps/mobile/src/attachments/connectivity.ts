import NetInfo from "@react-native-community/netinfo";
import type { Connectivity } from "@vesta/core";

// The upload engine parks on the connectivity edge (no timers burn offline, the online edge
// resumes), so it wants an event source, not a poll. NetInfo's listener is that source; the
// latest answer is cached so isOnline stays synchronous.

interface NetInfoLike {
  addEventListener: (
    listener: (state: { isConnected: boolean | null }) => void,
  ) => () => void;
}

export function createNetInfoConnectivity(net: NetInfoLike): Connectivity {
  let online = true;
  const listeners = new Set<(online: boolean) => void>();
  net.addEventListener((state) => {
    const next = state.isConnected ?? true;
    if (next === online) return;
    online = next;
    for (const listener of [...listeners]) listener(next);
  });
  return {
    isOnline: () => online,
    onChange: (callback) => {
      listeners.add(callback);
      return () => listeners.delete(callback);
    },
  };
}

let shared: Connectivity | null = null;

// One app-wide subscription: every upload engine shares the same cached answer and edge.
export function netInfoConnectivity(): Connectivity {
  shared ??= createNetInfoConnectivity(NetInfo);
  return shared;
}
