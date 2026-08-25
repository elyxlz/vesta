import { create } from "zustand";

// The app's one scrim (components/Scrim) shows while any floating surface
// holds it. Overlay roots acquire on open and release on close, so a handoff
// between two surfaces in one event (popover to dialog) never drops to zero
// holders and the scrim never flashes.
interface ScrimState {
  holders: number;
  acquire: () => void;
  release: () => void;
}

export const useScrim = create<ScrimState>((set) => ({
  holders: 0,
  acquire: () => {
    set((state) => ({ holders: state.holders + 1 }));
  },
  release: () => {
    set((state) => ({ holders: Math.max(0, state.holders - 1) }));
  },
}));
