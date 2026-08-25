import { type ReactNode } from "react";
import { useMotionValue } from "motion/react";
import { ToastPillContext } from "./context";

// Owns the toast pill's persistent piece, the morph width; the toast queue
// itself already persists in the zustand store. Living here (mounted once
// above the route layouts), the width survives page navigation while the
// navbars, and the ToastPill they render, remount per layout.
export function ToastPillProvider({ children }: { children: ReactNode }) {
  const morphWidth = useMotionValue(0);

  return (
    <ToastPillContext.Provider value={{ morphWidth }}>
      {children}
    </ToastPillContext.Provider>
  );
}
