import { useMemo } from "react";
import { motionValue, type MotionValue } from "motion/react";
import { create } from "zustand";

// How long a toast stays up before it auto-dismisses.
const TOAST_MS = 4000;

export type ToastKind = "error" | "success" | "info";

export interface Toast {
  id: string;
  kind: ToastKind;
  title: string;
}

interface ToastState {
  current: Toast | null;
  /**
   * The pill shell's animated width, held beside the queue so a navbar
   * remount on page navigation resumes mid-morph instead of replaying it.
   */
  morphWidth: MotionValue<number>;
  show: (kind: ToastKind, title: string) => void;
  dismiss: () => void;
}

// One toast at a time (like the notifications pill): a new one replaces the current, and each
// schedules its own id-guarded auto-dismiss, so a superseded toast's timer is a harmless no-op.
export const useToastStore = create<ToastState>((set) => ({
  current: null,
  morphWidth: motionValue(0),
  show: (kind, title) => {
    const id = crypto.randomUUID();
    set({ current: { id, kind, title } });
    setTimeout(() => {
      set((state) => (state.current?.id === id ? { current: null } : state));
    }, TOAST_MS);
  },
  dismiss: () => {
    set({ current: null });
  },
}));

export interface ToastApi {
  error: (message: string) => void;
  success: (message: string) => void;
  info: (message: string) => void;
}

// Consumers call useToast() for typed helpers; the ToastPill in the navbar renders the store.
export function useToast(): ToastApi {
  const show = useToastStore((state) => state.show);
  return useMemo(
    () => ({
      error: (message) => {
        show("error", message);
      },
      success: (message) => {
        show("success", message);
      },
      info: (message) => {
        show("info", message);
      },
    }),
    [show],
  );
}
