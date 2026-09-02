import {
  feedHasUnseen,
  splitBySeen,
  type LoggedUserNotification,
} from "./user-notification-feed";

// The user-notification feed as one state machine, shared by every view: the
// durable log's pages and the live `user_notification` edge join into a single
// id-keyed list (a live arrival and the page that later contains it are the
// same row), and the catch-up session holds the seen watermark it opened with.

/** The newest page's lifecycle; the skeletons show while it is `idle` or `loading` with no rows. */
type NewestPageStatus = "idle" | "loading" | "ready" | "failed";
/** Whether the archive extends past the oldest loaded row. */
type OlderPagesStatus = "more" | "loading" | "exhausted" | "failed";

export interface NotificationFeed {
  /** Newest first, unique by id. */
  entries: LoggedUserNotification[];
  /** Rows that arrived over the socket during this session (the ones a view animates in). */
  liveIds: number[];
  /** Rows the user watched arrive in the chat, which is why they never raise the bell's dot. */
  readIds: number[];
  newest: NewestPageStatus;
  older: OlderPagesStatus;
  /** A history surface is on screen. */
  open: boolean;
  /**
   * The seen watermark as it stood when the latest session opened, kept after
   * close so a surface animating out renders exactly what it showed; null
   * before the first session ever. 0 means the user never caught up.
   */
  seenAt: number | null;
  /**
   * The stamp the last close optimistically marked seen up to, so the bell's dot
   * stays down from close until the gateway's synced watermark catches up over a
   * slow link. Monotonic; a newer arrival always out-stamps it and re-raises the dot.
   */
  pendingSeenAt: number | null;
}

export const EMPTY_FEED: NotificationFeed = {
  entries: [],
  liveIds: [],
  readIds: [],
  newest: "idle",
  older: "more",
  open: false,
  seenAt: null,
  pendingSeenAt: null,
};

export type FeedAction =
  | { type: "open"; seenAt: number }
  | { type: "close" }
  | { type: "marked_seen"; seenAt: number }
  | { type: "arrived"; entry: LoggedUserNotification; readInPlace: boolean }
  | { type: "page_loading"; before?: number }
  | {
      type: "page_loaded";
      page: LoggedUserNotification[];
      before?: number;
      pageSize: number;
    }
  | { type: "page_failed"; before?: number };

export function reduceFeed(
  feed: NotificationFeed,
  action: FeedAction,
): NotificationFeed {
  switch (action.type) {
    case "open":
      // Both annotations are dropped: closing this session marks the whole feed
      // seen, so nothing loaded now can raise the dot again.
      if (feed.open) return feed;
      return {
        ...feed,
        open: true,
        seenAt: action.seenAt,
        liveIds: [],
        readIds: [],
      };
    case "close":
      return { ...feed, open: false };
    case "marked_seen":
      return {
        ...feed,
        pendingSeenAt: Math.max(feed.pendingSeenAt ?? 0, action.seenAt),
      };
    case "arrived":
      if (feed.entries.some((item) => item.id === action.entry.id)) return feed;
      return {
        ...feed,
        entries: merge(feed.entries, [action.entry]),
        liveIds: [...feed.liveIds, action.entry.id],
        readIds: action.readInPlace
          ? [...feed.readIds, action.entry.id]
          : feed.readIds,
      };
    case "page_loading":
      return action.before === undefined
        ? { ...feed, newest: "loading" }
        : { ...feed, older: "loading" };
    case "page_loaded": {
      const short = action.page.length < action.pageSize;
      const entries = merge(feed.entries, action.page);
      if (action.before === undefined) {
        return {
          ...feed,
          entries,
          newest: "ready",
          older: short ? "exhausted" : feed.older,
        };
      }
      return { ...feed, entries, older: short ? "exhausted" : "more" };
    }
    case "page_failed":
      return action.before === undefined
        ? { ...feed, newest: "failed" }
        : { ...feed, older: "failed" };
  }
}

function merge(
  existing: LoggedUserNotification[],
  incoming: LoggedUserNotification[],
): LoggedUserNotification[] {
  const byId = new Map(existing.map((item) => [item.id, item]));
  for (const item of incoming) byId.set(item.id, item);
  return [...byId.values()].sort((a, b) => b.id - a.id);
}

/**
 * Whether closing the session should tell the gateway the user caught up:
 * something is past the held watermark, by the gateway's newest stamp or by a
 * loaded row (a live arrival can land before the stamp's own delta).
 */
export function feedNeedsMarkSeen(
  feed: NotificationFeed,
  lastAt: number | null,
): boolean {
  if (feed.seenAt === null) return false;
  const seenAt = feed.seenAt;
  return (
    feedHasUnseen(lastAt, seenAt) ||
    feed.entries.some((item) => item.at > seenAt)
  );
}

/**
 * Whether the bell wears its dot: something past the gateway's watermark that the
 * user has not already read where it happened. The gateway's two scalars answer
 * first, and the loaded rows then discount the ones read in the chat. Anything the
 * client cannot account for (the newest page not loaded yet, or a stamp above every
 * row it holds) keeps the dot, so the derivation only ever hides a row it has.
 */
export function feedUnseen(
  feed: NotificationFeed,
  lastAt: number | null | undefined,
  seenAt: number | undefined,
): boolean {
  // The last close's optimistic floor holds the dot down until the synced watermark catches up.
  const watermark = Math.max(seenAt ?? 0, feed.pendingSeenAt ?? 0);
  if (!feedHasUnseen(lastAt, watermark)) return false;
  if (feed.newest !== "ready") return true;
  const newest = feed.entries[0];
  if ((lastAt ?? 0) > (newest === undefined ? 0 : newest.at)) return true;
  const read = new Set(feed.readIds);
  return feed.entries.some((item) => item.at > watermark && !read.has(item.id));
}

/** The unseen/seen split, or null when the feed renders as one plain list. */
export type FeedSections = {
  unseen: LoggedUserNotification[];
  seen: LoggedUserNotification[];
} | null;

/**
 * The unseen/seen split against the held watermark, or null when the feed
 * renders as one plain list: before the first session, and for a user who
 * never caught up (everything would be "new", so a split only adds noise).
 */
export function feedSections(feed: NotificationFeed): FeedSections {
  if (feed.seenAt === null || feed.seenAt === 0) return null;
  return splitBySeen(feed.entries, feed.seenAt);
}

export type FeedView = "loading" | "failed" | "empty" | "rows";

/** What a history surface shows: rows whenever there are any, else the newest page's state. */
export function feedView(feed: NotificationFeed): FeedView {
  if (feed.entries.length > 0) return "rows";
  if (feed.newest === "failed") return "failed";
  if (feed.newest === "ready") return "empty";
  return "loading";
}
