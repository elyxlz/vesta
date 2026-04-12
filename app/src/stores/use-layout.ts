import { create } from "zustand";

const isMacOS = document.documentElement.dataset.platform === "macos";

interface LayoutState {
  navbarHeight: number;
  bottomBarHeight: number;
  setNavbarHeight: (height: number) => void;
  setBottomBarHeight: (height: number) => void;
}

export const useLayout = create<LayoutState>((set) => ({
  navbarHeight: isMacOS ? 68 : 44,
  bottomBarHeight: 0,
  setNavbarHeight: (height) => set({ navbarHeight: height }),
  setBottomBarHeight: (height) => set({ bottomBarHeight: height }),
}));
