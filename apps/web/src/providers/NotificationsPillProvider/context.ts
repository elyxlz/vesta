import { createContext, useContext } from "react";
import type { MotionValue } from "motion/react";
import type {
  LoggedUserNotification,
  PillContent,
  PillNotification,
} from "@vesta/core";

// The pill's two morph dimensions, shared by the provider (which owns the
// persistent motion values) and the navbar rendering: the idle state is the
// standard 40px navbar icon button, the expanded pill sits slightly slimmer.
export const PILL_BUTTON_SIZE = 40;
export const PILL_EXPANDED_HEIGHT = 38;

// Context + hook live apart from the provider component so the context
// identity is stable across Fast Refresh (matches ControllerProvider).

export interface NotificationHistory {
  history: LoggedUserNotification[];
  exhausted: boolean;
  loading: boolean;
  failed: boolean;
  loadPage: (before?: number) => void;
  ensure: () => void;
  prepend: (item: PillContent) => void;
}

export interface NotificationsPillState {
  current: PillNotification | null;
  dismiss: () => void;
  /**
   * A notification arrived since the user last opened a history surface. The
   * compact (mobile) bell renders it as a dot; opening the popover or dialog
   * clears it.
   */
  unseen: boolean;
  feed: NotificationHistory;
  popoverOpen: boolean;
  setPopoverOpen: (open: boolean) => void;
  dialogOpen: boolean;
  setDialogOpen: (open: boolean) => void;
  /** Dismiss the shown notification and open its agent (home when none). */
  openAgent: (agent: string) => void;
  /** Open a history entry's agent, dismissing whichever surface showed it. */
  openEntry: (entry: LoggedUserNotification) => void;
  /**
   * The shell's animated dimensions, owned here so a navbar remount on page
   * navigation resumes from the current size instead of re-running the morph.
   */
  morph: { width: MotionValue<number>; height: MotionValue<number> };
}

// Live-arrival entries (prepended while a history surface is open) carry
// synthetic ids counting down from the top of the safe integer range; entries
// fetched from the log sit far below. Only live entries animate into the list.
export function isLivePillEntry(id: number): boolean {
  return id > Number.MAX_SAFE_INTEGER / 2;
}

export const NotificationsPillContext =
  createContext<NotificationsPillState | null>(null);

export function useNotificationsPillState(): NotificationsPillState {
  const state = useContext(NotificationsPillContext);
  if (!state) {
    throw new Error(
      "useNotificationsPillState must be used within NotificationsPillProvider",
    );
  }
  return state;
}
