import { create } from "zustand";

interface LayoutState {
  navbarHeight: number;
  chatHeaderStripBottomPx: number;
  setNavbarHeight: (height: number) => void;
  setChatHeaderStripBottomPx: (height: number) => void;
}

export const useLayout = create<LayoutState>((set) => ({
  navbarHeight: 44,
  chatHeaderStripBottomPx: 0,
  setNavbarHeight: (height) => set({ navbarHeight: height }),
  setChatHeaderStripBottomPx: (height) => set({ chatHeaderStripBottomPx: height }),
}));
