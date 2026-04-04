import { create } from "zustand";

interface LayoutState {
  navbarHeight: number;
  setNavbarHeight: (height: number) => void;
}

export const useLayout = create<LayoutState>((set) => ({
  navbarHeight: 44,
  setNavbarHeight: (height) => set({ navbarHeight: height }),
}));
