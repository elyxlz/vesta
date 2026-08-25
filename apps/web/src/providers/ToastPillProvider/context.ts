import { createContext } from "react";
import type { MotionValue } from "motion/react";

// Context lives apart from the provider component so its identity is stable
// across Fast Refresh (matches NotificationsPillProvider). Nullable on
// purpose: surfaces outside the router render the toast shell with a local,
// non-persistent width instead.
export interface ToastPillState {
  /**
   * The shell's animated width, owned above the route layouts so a navbar
   * remount on page navigation resumes from the current size instead of
   * re-running the morph.
   */
  morphWidth: MotionValue<number>;
}

export const ToastPillContext = createContext<ToastPillState | null>(null);
