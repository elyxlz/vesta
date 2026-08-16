// Keyed stale-while-remounting holds: one cell per agent+gateway key, living above navigation so
// per-agent view state survives screen pops and controller epochs. A bounded LRU keeps memory flat.
const MAX_HOLD_CELLS = 12;

export interface KeyedHoldStore<T> {
  read: (key: string) => T | null;
  persist: (key: string, value: T) => void;
}

export function createKeyedHoldStore<T>(): KeyedHoldStore<T> {
  const cells = new Map<string, T>();
  return {
    read: (key) => cells.get(key) ?? null,
    persist: (key, value) => {
      cells.delete(key);
      cells.set(key, value);
      if (cells.size > MAX_HOLD_CELLS) {
        const oldest = cells.keys().next();
        if (!oldest.done) cells.delete(oldest.value);
      }
    },
  };
}

// Hold cells are per-agent AND per-gateway: the key pins held state to both (via the gateway's
// connectionKeyOf) so a different agent or a switched gateway never seeds the wrong data.
export function agentHoldKey(agent: string, connectionKey: string): string {
  return `${agent}\n${connectionKey}`;
}
