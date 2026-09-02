import { dayKey, formatDayLabel } from "./feed-format";
import { motion } from "motion/react";
import { Fragment, useMemo } from "react";
import {
  feedView,
  type FeedSections,
  type FeedView,
  type LoggedUserNotification,
  type NotificationFeed,
} from "@vesta/core";
import { useGateway } from "@/providers/GatewayProvider/context";
import { cn } from "@/lib/utils";
import { NotificationRow, SectionLabel } from "./notification-row";
import { Skeleton } from "@/components/ui/skeleton";

const HISTORY_SKELETON_ROWS = 5;
// The compact popover under the bell is a taster: at most this many rows,
// with "see all" opening the full dialog.

// One rendering of the history (skeletons, rows, empty/error text) shared by
// the compact popover and the full dialog; the surfaces differ only in row
// budget, skeleton count, and footer.
export function HistoryList({
  view,
  liveIds,
  entries,
  emptyLabel,
  skeletonCount,
  footer,
  timestamps = false,
  compact = false,
  dimmed = false,
  onOpen,
}: {
  view: FeedView;
  liveIds: number[];
  /** The rows this surface renders (the popover passes only the unseen ones). */
  entries: LoggedUserNotification[];
  /** Caption when there are no rows and the feed has answered; null captions nothing. */
  emptyLabel: string | null;
  skeletonCount: number;
  footer?: React.ReactNode;
  timestamps?: boolean;
  compact?: boolean;
  /** The dialog's already-seen section renders its rows sat back. */
  dimmed?: boolean;
  onOpen: (entry: LoggedUserNotification) => void;
}) {
  const emptyText = entries.length > 0 ? null : emptyCaption(view, emptyLabel);
  // Resolve the agent per row from one roster read, so rows don't each
  // subscribe to the gateway and scan it; live only slides in fresh arrivals.
  const { agents } = useGateway();
  const agentByName = useMemo(
    () => new Map(agents.map((agent) => [agent.name, agent])),
    [agents],
  );
  const liveSet = useMemo(() => new Set(liveIds), [liveIds]);
  return (
    <>
      {view === "loading" && <SkeletonRows count={skeletonCount} />}
      {/* The pill's rotary, as a list: a row arriving slides in from above
          while `layout` glides the rest down to make room. In the dialog
          (timestamps on), a date label opens each day's group, so the rows'
          own stamps carry the time alone. */}
      {entries.map((entry, index) => {
        const previous = index > 0 ? entries[index - 1] : undefined;
        const opensDay =
          timestamps && (!previous || dayKey(previous.at) !== dayKey(entry.at));
        const dayLabel = opensDay ? formatDayLabel(entry.at) : "";
        return (
          <Fragment key={entry.id}>
            {dayLabel && (
              <div className="px-2 pt-5 pb-3 text-center text-xs text-muted-foreground">
                {dayLabel}
              </div>
            )}
            <motion.div
              layout
              // Only a live arrival slides in; rows loaded from the log (the
              // first page after the skeletons, and older pages) just appear.
              initial={liveSet.has(entry.id) ? { y: -24, opacity: 0 } : false}
              animate={{ y: 0, opacity: 1 }}
              transition={{ type: "spring", duration: 0.35, bounce: 0 }}
            >
              <NotificationRow
                entry={entry}
                row={agentByName.get(entry.agent) ?? null}
                timestamp={timestamps}
                compact={compact}
                dimmed={dimmed}
                banded={timestamps && index % 2 === 0}
                onOpen={onOpen}
              />
            </motion.div>
          </Fragment>
        );
      })}
      {emptyText && (
        <p
          className={cn(
            "px-2 text-center text-muted-foreground",
            compact ? "py-4 text-[13px]" : "py-5 text-sm",
          )}
        >
          {emptyText}
        </p>
      )}
      {footer}
    </>
  );
}

// A failed first load captions the list as unloadable; a failed "load older"
// under loaded rows keeps its button instead (the view reads rows then).

// A failed first load captions the list as unloadable; a failed "load older"
// under loaded rows keeps its button instead (the view reads rows then).
function emptyCaption(
  view: FeedView,
  emptyLabel: string | null,
): string | null {
  if (view === "loading") return null;
  if (view === "failed") return "couldn't load notifications";
  return emptyLabel;
}

// Whether the archive holds more than the popover's taster, which is what
// earns the "see all" footer. Read from the cached rows alone, never the
// refetch every open starts, so the footer is there the instant the popover
// is.

export function DialogHistory({
  feed,
  sections,
  footer,
  onOpen,
}: {
  feed: NotificationFeed;
  sections: FeedSections;
  footer?: React.ReactNode;
  onOpen: (entry: LoggedUserNotification) => void;
}) {
  const view = feedView(feed);
  if (!sections || sections.unseen.length === 0) {
    return (
      <HistoryList
        view={view}
        liveIds={feed.liveIds}
        entries={feed.entries}
        emptyLabel="no notifications yet"
        skeletonCount={HISTORY_SKELETON_ROWS}
        footer={footer}
        timestamps
        onOpen={onOpen}
      />
    );
  }
  return (
    <>
      <SectionLabel text="new" />
      <HistoryList
        view={view}
        liveIds={feed.liveIds}
        entries={sections.unseen}
        emptyLabel={null}
        skeletonCount={0}
        timestamps
        onOpen={onOpen}
      />
      {(sections.seen.length > 0 || feed.older !== "exhausted") && (
        <SectionLabel text="earlier" />
      )}
      <HistoryList
        view={view}
        liveIds={feed.liveIds}
        entries={sections.seen}
        emptyLabel={null}
        skeletonCount={0}
        footer={footer}
        timestamps
        dimmed
        onOpen={onOpen}
      />
    </>
  );
}

function SkeletonRows({ count }: { count: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="flex items-center gap-2.5 px-2 py-2">
          <Skeleton className="size-4 rounded-full" />
          <Skeleton className="h-4 flex-1 rounded-lg" />
          <Skeleton className="h-3 w-12 rounded-lg" />
        </div>
      ))}
    </>
  );
}

// Rendered as the popover trigger (`asChild`): Radix merges its toggle
// handler and ref into the button; a click while a notification shows opens
// its agent and skips the toggle.
