import { createStore, type StoreApi } from "zustand/vanilla";

// Keyed stale-while-remounting holds: one cell per agent+gateway key, living above navigation so
// per-agent view state survives screen pops, route unmounts, and controller epochs. A bounded LRU
// keeps memory flat. The cells live in a zustand store so a React consumer can subscribe to one
// key (`useHeld` in the react entry) while imperative readers seed from `read`.
const MAX_HOLD_CELLS = 12;

interface HeldCells<T> {
  readonly cells: ReadonlyMap<string, T>;
}

export interface KeyedHoldStore<T> {
  readonly store: StoreApi<HeldCells<T>>;
  read: (key: string) => T | null;
  persist: (key: string, value: T) => void;
}

export function createKeyedHoldStore<T>(): KeyedHoldStore<T> {
  const store = createStore<HeldCells<T>>(() => ({ cells: new Map() }));
  return {
    store,
    read: (key) => store.getState().cells.get(key) ?? null,
    persist: (key, value) => {
      const cells = new Map(store.getState().cells);
      cells.delete(key);
      cells.set(key, value);
      if (cells.size > MAX_HOLD_CELLS) {
        const oldest = cells.keys().next();
        if (!oldest.done) cells.delete(oldest.value);
      }
      store.setState({ cells });
    },
  };
}

// Hold cells are per-agent AND per-gateway: the key pins held state to both so a different agent
// or a switched gateway never seeds the wrong data.
export function agentHoldKey(agent: string, connectionKey: string): string {
  return `${agent}\n${connectionKey}`;
}
