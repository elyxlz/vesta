import { create } from "zustand";

const isMacOS = document.documentElement.dataset.platform === "macos";

interface LayoutState {
  navbarHeight: number;
  bottomBarHeight: number;
  chatKeyboardFocused: boolean;
  setNavbarHeight: (height: number) => void;
  setBottomBarHeight: (height: number) => void;
  setChatKeyboardFocused: (focused: boolean) => void;
}

export const useLayout = create<LayoutState>((set) => ({
  navbarHeight: isMacOS ? 68 : 44,
  bottomBarHeight: 0,
  chatKeyboardFocused: false,
  setNavbarHeight: (height) => set({ navbarHeight: height }),
  setBottomBarHeight: (height) => set({ bottomBarHeight: height }),
  setChatKeyboardFocused: (focused) => set({ chatKeyboardFocused: focused }),
}));
