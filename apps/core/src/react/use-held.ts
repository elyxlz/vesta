import { useStore } from "zustand";
import type { KeyedHoldStore } from "../holds/keyed-hold";

// Subscribes to one hold cell, so every mounted consumer of the same key renders the same value.
export function useHeld<T>(hold: KeyedHoldStore<T>, key: string): T | null {
  return useStore(hold.store, (state) => state.cells.get(key) ?? null);
}
