import { create } from "zustand";

const isMacOS = document.documentElement.dataset.platform === "macos";

// The floating composer's baseline (empty) height, cached per layout so a remounted
// chat reserves the right space on its first render instead of measuring it a frame
// later and snapping the bubbles up. One slot per variant: their paddings differ.
export type ComposerVariant = "panel" | "fullscreen" | "mobile";

interface LayoutState {
  navbarHeight: number;
  bottomBarHeight: number;
  chatKeyboardFocused: boolean;
  composerBaseline: Record<ComposerVariant, number>;
  setNavbarHeight: (height: number) => void;
  setBottomBarHeight: (height: number) => void;
  setChatKeyboardFocused: (focused: boolean) => void;
  setComposerBaseline: (variant: ComposerVariant, height: number) => void;
}

export const useLayout = create<LayoutState>((set) => ({
  navbarHeight: isMacOS ? 68 : 44,
  bottomBarHeight: 0,
  chatKeyboardFocused: false,
  composerBaseline: { panel: 0, fullscreen: 0, mobile: 0 },
  setNavbarHeight: (height) => set({ navbarHeight: height }),
  setBottomBarHeight: (height) => set({ bottomBarHeight: height }),
  setChatKeyboardFocused: (focused) => set({ chatKeyboardFocused: focused }),
  setComposerBaseline: (variant, height) =>
    set((state) => ({
      composerBaseline: { ...state.composerBaseline, [variant]: height },
    })),
}));
