import { createContext } from "react";
import type { MotionValue } from "motion/react";
import type {
  LoggedUserNotification,
  NotificationFeed,
  PillNotification,
} from "@vesta/core";

// The pill's two morph dimensions, shared by the provider (which owns the
// persistent motion values) and the navbar rendering: the idle state is the
// standard 40px navbar icon button, the expanded pill sits slightly slimmer.
export const PILL_BUTTON_SIZE = 40;
export const PILL_EXPANDED_HEIGHT = 38;

/** Which history surface is on screen; popover and dialog share one catch-up session. */
export type HistorySurface = "none" | "popover" | "dialog";

export interface NotificationsPillState {
  current: PillNotification | null;
  dismiss: () => void;
  /**
   * Something in the feed is past the synced seen watermark. The compact
   * (mobile) bell renders it as a dot; it clears when any device catches up
   * (closes a history surface), including this one.
   */
  unseen: boolean;
  /** The shared feed model: rows, page states, and the held watermark. */
  feed: NotificationFeed;
  loadOlder: () => void;
  surface: HistorySurface;
  showSurface: (surface: HistorySurface) => void;
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

export const NotificationsPillContext =
  createContext<NotificationsPillState | null>(null);
