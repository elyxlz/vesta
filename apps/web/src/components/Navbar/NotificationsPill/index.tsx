import { animate, AnimatePresence, motion } from "motion/react";
import {
  Activity,
  Bell,
  CircleAlert,
  CircleArrowUp,
  MessageSquare,
  MonitorSmartphone,
  Sparkles,
  SquareCheck,
  type LucideIcon,
} from "lucide-react";
import { Fragment, useContext, useLayoutEffect, useRef } from "react";
import {
  PILL_FALLBACK_ICON,
  PILL_KIND_ICONS,
  pillDisplayLine,
  splitBySeen,
  type LoggedUserNotification,
  type PillNotification,
} from "@vesta/core";
import {
  isLivePillEntry,
  NotificationsPillContext,
  PILL_BUTTON_SIZE,
  PILL_EXPANDED_HEIGHT,
  type NotificationHistory,
  type NotificationsPillState,
} from "@/providers/NotificationsPillProvider/context";
import { useGateway } from "@/providers/GatewayProvider/context";
import { calendarDayKey, formatChatDayStampLabel } from "@/lib/chat-day-stamp";
import { useIsMobile } from "@/hooks/use-mobile";
import { useOrbStatus } from "@/hooks/use-orb-state";
import { Orb } from "@/components/Orb";
import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/ui/popover";

// Layout and motion are this app's own (mobile renders the shared model its
// own way): the idle button size, the resize/slide sequencing beat, the width
// cap, and the history page size.
// Idle: the standard 40px navbar icon button (the home button's size); showing
// a notification, the shell morphs to the slimmer pill height.
const RESIZE_DELAY_S = 0.35;
const PILL_MAX_WIDTH = 340;
const HISTORY_SKELETON_ROWS = 5;
// The compact popover under the bell shows this many before "see more".
const POPOVER_ROWS = 6;

// This app's rendering of the core icon names (PILL_KIND_ICONS): the shared
// vocabulary is view-independent, and each view maps it onto its own icon set.
const ICON_COMPONENTS: Record<string, LucideIcon> = {
  "message-square": MessageSquare,
  "circle-alert": CircleAlert,
  "square-check": SquareCheck,
  activity: Activity,
  sparkles: Sparkles,
  "circle-arrow-up": CircleArrowUp,
  "monitor-smartphone": MonitorSmartphone,
  bell: Bell,
};

// The navbar's ambient notification surface, anchored beside the leading
// buttons: an idle bell button that morphs into the pill while notifications
// rotate through, and back once the queue drains. Tapping a shown notification
// opens its agent; tapping the idle bell opens a compact popover of recent
// history under the button, whose "see more" expands into the full dialog over
// the durable log. All state lives in NotificationsPillProvider (mounted above
// the route layouts, so navigation never resets it); this component is only
// the web rendering.

// One rendering of the history (skeletons, rows, empty/error text) shared by
// the compact popover and the full dialog; the surfaces differ only in row
// budget, skeleton count, and footer.
function HistoryList({
  state,
  entries,
  emptyLabel,
  skeletonCount,
  footer,
  timestamps = false,
  compact = false,
  onOpen,
}: {
  state: NotificationHistory;
  /** The rows this surface renders (the popover passes only the unseen ones). */
  entries: LoggedUserNotification[];
  /** Caption when there are no rows and nothing is loading; null captions nothing. */
  emptyLabel: string | null;
  skeletonCount: number;
  footer?: React.ReactNode;
  timestamps?: boolean;
  compact?: boolean;
  onOpen: (entry: LoggedUserNotification) => void;
}) {
  const { history, loading, failed } = state;
  const shown = entries;
  // A failed first load captions the list as unloadable; a failed "load older"
  // under loaded rows keeps its button instead.
  const emptyText =
    shown.length > 0
      ? null
      : failed && history.length === 0
        ? "couldn't load notifications"
        : emptyLabel;
  return (
    <>
      {loading && history.length === 0 && (
        <SkeletonRows count={skeletonCount} />
      )}
      {/* The pill's rotary, as a list: a row arriving slides in from above
          while `layout` glides the rest down to make room. In the dialog
          (timestamps on), a date label opens each day's group, so the rows'
          own stamps carry the time alone. */}
      {shown.map((entry, index) => {
        const previous = index > 0 ? shown[index - 1] : undefined;
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
              initial={
                isLivePillEntry(entry.id) ? { y: -24, opacity: 0 } : false
              }
              animate={{ y: 0, opacity: 1 }}
              transition={{ type: "spring", duration: 0.35, bounce: 0 }}
            >
              <NotificationRow
                entry={entry}
                timestamp={timestamps}
                compact={compact}
                onOpen={onOpen}
              />
            </motion.div>
          </Fragment>
        );
      })}
      {emptyText && !loading && (
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

type SeenSplit = ReturnType<typeof splitBySeen>;

// Whether the archive holds more than the popover is showing, which is what
// earns the "see all" footer. Before the first-ever catch-up (no split) the
// popover caps at POPOVER_ROWS, so the archive extends past it sooner.
function archiveExtendsBeyond(
  feed: NotificationHistory,
  split: SeenSplit | null,
): boolean {
  if (split) return feed.history.length > 0 || !feed.exhausted;
  return (
    feed.history.length > 0 &&
    (feed.history.length > POPOVER_ROWS || !feed.exhausted)
  );
}

function popoverEmptyLabel(
  split: SeenSplit | null,
  exhausted: boolean,
): string | null {
  if (split) return "you're all caught up";
  return exhausted ? "no notifications yet" : null;
}

// The dialog's body: the unseen/seen sections while the session's watermark
// splits the history, the plain list otherwise (including before the
// first-ever catch-up, where everything would be "new").
function DialogHistory({
  feed,
  split,
  footer,
  onOpen,
}: {
  feed: NotificationHistory;
  split: SeenSplit | null;
  footer?: React.ReactNode;
  onOpen: (entry: LoggedUserNotification) => void;
}) {
  if (!split || split.unseen.length === 0) {
    return (
      <HistoryList
        state={feed}
        entries={feed.history}
        emptyLabel={feed.exhausted ? "no notifications yet" : null}
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
        state={feed}
        entries={split.unseen}
        emptyLabel={null}
        skeletonCount={0}
        timestamps
        onOpen={onOpen}
      />
      {(split.seen.length > 0 || !feed.exhausted) && (
        <SectionLabel text="earlier" />
      )}
      <HistoryList
        state={feed}
        entries={split.seen}
        emptyLabel={null}
        skeletonCount={0}
        footer={footer}
        timestamps
        onOpen={onOpen}
      />
    </>
  );
}

export function NotificationsPill() {
  // Nullable on purpose: the version-gate screens render the navbar outside
  // the router and the provider, where the pill degrades to a static bell.
  const state = useContext(NotificationsPillContext);
  if (!state) {
    return (
      <div className="chrome-outline flex size-10 items-center justify-center rounded-full">
        <Bell className="size-4 shrink-0" aria-hidden />
      </div>
    );
  }
  return <ConnectedNotificationsPill state={state} />;
}

function ConnectedNotificationsPill({
  state,
}: {
  state: NotificationsPillState;
}) {
  // Narrow layouts have no room for the morph: the bell stays a plain button
  // and arrivals raise a dot on it instead of rotating through a pill.
  const isMobile = useIsMobile();
  const {
    current,
    feed,
    seenSnapshot,
    popoverOpen,
    setPopoverOpen,
    dialogOpen,
    setDialogOpen,
    openAgent,
    openEntry,
  } = state;

  // The awareness-feed split, against the watermark held for this catch-up
  // session. A 0 watermark (the user never caught up) renders unsectioned:
  // everything ever logged is "unseen", so a split would only add noise.
  const caughtUpBefore = seenSnapshot !== null && seenSnapshot > 0;
  const split = caughtUpBefore ? splitBySeen(feed.history, seenSnapshot) : null;

  // The bell is a toggle: a click that began while the popover was open is
  // the close half (Radix's outside-pointerdown already dismissed it), so it
  // must not re-open, and must not touch the feed, or a failed first load
  // would flash its skeletons into the closing popover.
  const openWasOpenRef = useRef(false);
  const onHistoryPointerDown = () => {
    openWasOpenRef.current = popoverOpen;
  };
  const openPopover = () => {
    if (openWasOpenRef.current) {
      openWasOpenRef.current = false;
      return;
    }
    feed.ensure();
    setPopoverOpen(true);
  };

  // The popover shows the whole unseen set (scrolling past its cap), or, before
  // the first-ever catch-up, the newest page the way the dialog would.
  const popoverEntries = split
    ? split.unseen
    : feed.history.slice(0, POPOVER_ROWS);

  // "see all" opens the dialog over the full archive; it rides the same slide
  // the rows do, one block.
  const seeAll = !feed.loading &&
    !feed.failed &&
    archiveExtendsBeyond(feed, split) && (
      <motion.div layout>
        <Button
          variant="ghost"
          size="xs"
          className="w-full text-[13px] text-muted-foreground"
          onClick={() => {
            // Dialog first, popover after: historyOpen never blips false, so the
            // catch-up session (and its held watermark) carries over.
            setDialogOpen(true);
            setPopoverOpen(false);
          }}
        >
          see all
        </Button>
      </motion.div>
    );

  const loadOlder = !feed.exhausted && feed.history.length > 0 && (
    <Button
      variant="ghost"
      className="w-full text-xs text-muted-foreground"
      disabled={feed.loading}
      onClick={() => {
        const oldest = feed.history[feed.history.length - 1];
        if (oldest) feed.loadPage(oldest.id);
      }}
    >
      {feed.loading ? "loading..." : "load older"}
    </Button>
  );

  return (
    <>
      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <PopoverAnchor>
          {isMobile ? (
            <CompactBell
              unseen={state.unseen}
              onOpenHistory={openPopover}
              onHistoryPointerDown={onHistoryPointerDown}
            />
          ) : (
            <MorphingPill
              current={current}
              morph={state.morph}
              onOpenAgent={openAgent}
              onOpenHistory={openPopover}
              onHistoryPointerDown={onHistoryPointerDown}
            />
          )}
        </PopoverAnchor>
        {/* Above the navbar layer (z-[99999]), where the toast lives: an open
            history must not have toasts floating over it. */}
        <PopoverContent align="center" className="z-[100000] w-58 p-2">
          <div className="max-h-[60vh] space-y-1 overflow-y-auto">
            <HistoryList
              state={feed}
              entries={popoverEntries}
              emptyLabel={popoverEmptyLabel(split, feed.exhausted)}
              skeletonCount={POPOVER_ROWS}
              footer={seeAll}
              compact
              onOpen={openEntry}
            />
          </div>
        </PopoverContent>
      </Popover>
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>notifications</DialogTitle>
          </DialogHeader>
          <div className="space-y-1">
            <DialogHistory
              feed={feed}
              split={split}
              footer={loadOlder}
              onOpen={openEntry}
            />
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

// The dialog's unseen/seen boundary, styled as the day separators are.
function SectionLabel({ text }: { text: string }) {
  return (
    <div className="px-2 pt-5 pb-3 text-center text-xs text-muted-foreground">
      {text}
    </div>
  );
}

// Rows carry the time alone; the day lives in the date separators above them.
const TIME_FORMAT = new Intl.DateTimeFormat([], {
  hour: "2-digit",
  minute: "2-digit",
});

function formatTimestamp(atSeconds: number): string {
  return TIME_FORMAT.format(new Date(atSeconds * 1000));
}

function dayKey(atSeconds: number): string | null {
  return calendarDayKey(new Date(atSeconds * 1000).toISOString());
}

// Today's group carries no label (the freshest rows just start); the labels
// begin at yesterday, then fall to the chat's day-stamp rule so the two
// history surfaces date rows identically.
function formatDayLabel(atSeconds: number): string {
  const date = new Date(atSeconds * 1000);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return "";
  if (date.toDateString() === yesterday.toDateString()) return "yesterday";
  return formatChatDayStampLabel(date.toISOString());
}

// The persistent shell: a bell button at rest, widening into the pill while a
// notification shows. The shell owns its width as a motion value: each rotated
// item (the bell included) is measured as it lands, and the shell springs to
// that width. Rotation order depends on direction: an expanding shell resizes
// first and delays the incoming slide, a shrinking one slides first and delays
// the resize, so the text is never clipped by a shell that has not made room.
function NotificationRow({
  entry,
  timestamp,
  compact,
  onOpen,
}: {
  entry: LoggedUserNotification;
  timestamp: boolean;
  compact: boolean;
  onOpen: (entry: LoggedUserNotification) => void;
}) {
  // The pill's leading-glyph rule, identically: the orb when the notification
  // names a roster agent (who, at their current state), the kind icon
  // otherwise (what).
  const { agents } = useGateway();
  const row = agents.find((agent) => agent.name === entry.agent) ?? null;
  const { orbState } = useOrbStatus(row, row?.activityState ?? "idle");
  return (
    <button
      type="button"
      className={cn(
        "flex w-full items-center gap-2.5 overflow-hidden rounded-xl px-2 text-left hover:bg-muted",
        compact ? "py-1.5" : "py-2",
      )}
      onClick={() => {
        onOpen(entry);
      }}
    >
      {row ? (
        <span className="shrink-0">
          <Orb state={orbState} size={22} suppressMotion label={entry.agent} />
        </span>
      ) : (
        <PillKindIcon kind={entry.kind} />
      )}
      <div
        className={cn(
          "min-w-0 flex-1 truncate",
          compact ? "text-[13px]" : "text-sm",
        )}
      >
        {pillDisplayLine(entry)}
      </div>
      {timestamp && (
        <span className="shrink-0 text-[10px] text-muted-foreground">
          {formatTimestamp(entry.at)}
        </span>
      )}
    </button>
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

function MorphingPill({
  current,
  morph,
  onOpenAgent,
  onOpenHistory,
  onHistoryPointerDown,
}: {
  current: PillNotification | null;
  morph: NotificationsPillState["morph"];
  onOpenAgent: (agent: string) => void;
  onOpenHistory: () => void;
  onHistoryPointerDown: () => void;
}) {
  // Persistent (provider-owned) so a navbar remount resumes mid-morph.
  const { width, height } = morph;
  const contentRef = useRef<HTMLSpanElement | null>(null);
  const contentKey = current ? String(current.id) : "bell";
  const isPill = current !== null;

  useLayoutEffect(() => {
    const content = contentRef.current;
    if (!content) return;
    const target = Math.min(content.offsetWidth, PILL_MAX_WIDTH);
    const expanding = target > width.get();
    // Returning to idle (the bell) sequences nothing: it morphs back at once.
    const resize = {
      type: "spring",
      duration: 0.5,
      bounce: 0.2,
      delay: expanding || !isPill ? 0 : RESIZE_DELAY_S,
    } as const;
    const widthControls = animate(width, target, resize);
    const heightControls = animate(
      height,
      isPill ? PILL_EXPANDED_HEIGHT : PILL_BUTTON_SIZE,
      resize,
    );
    const slideControls = animate(
      content,
      { y: 0, opacity: 1 },
      {
        type: "spring",
        duration: 0.35,
        bounce: 0,
        delay: expanding ? RESIZE_DELAY_S : 0,
      },
    );
    return () => {
      widthControls.stop();
      heightControls.stop();
      slideControls.stop();
    };
  }, [contentKey, isPill, width, height]);

  return (
    <motion.button
      type="button"
      aria-label={current ? `open ${current.agent || "home"}` : "notifications"}
      // relative makes the shell the containing block for the popped (exiting)
      // line, which is what lets overflow-hidden actually clip the slide; the
      // centering keeps both sides shrinking or growing symmetrically while
      // the shell's width lags the content.
      className="chrome-outline relative flex items-center justify-center overflow-hidden rounded-full"
      style={{ width, height }}
      onPointerDown={onHistoryPointerDown}
      onClick={() => {
        if (current) onOpenAgent(current.agent);
        else onOpenHistory();
      }}
    >
      {/* The rotary: the shell holds while each item slides up and out as the
          next slides in from below; popLayout keeps the exiting one out of
          flow, and the incoming one (w-max) is what gets measured. */}
      <AnimatePresence initial={false} mode="popLayout">
        <motion.span
          key={contentKey}
          ref={contentRef}
          className={cn(
            "flex h-full shrink-0 items-center",
            current ? "w-max gap-1.5 px-3" : "w-10 justify-center",
          )}
          style={{ maxWidth: PILL_MAX_WIDTH }}
          // The slide-in runs imperatively from the measuring effect above (its
          // delay depends on the resize direction); only the exit is declared.
          // The bell leaves with a plain fade: it is not part of the rotary.
          initial={{ y: 24, opacity: 0 }}
          exit={current ? { y: -24, opacity: 0 } : { opacity: 0 }}
          transition={{ type: "spring", duration: 0.35, bounce: 0 }}
        >
          {current ? (
            <>
              {/* One leading glyph: the orb when the notification names a
                  roster agent (who), the kind icon otherwise (what). */}
              {current.orbState ? (
                <span className="shrink-0">
                  <Orb
                    state={current.orbState}
                    size={22}
                    suppressMotion
                    label={current.agent}
                  />
                </span>
              ) : (
                <PillKindIcon kind={current.kind} />
              )}
              <span className="min-w-0 truncate text-[13px]">
                {pillDisplayLine(current)}
              </span>
            </>
          ) : (
            <Bell className="size-4 shrink-0" aria-hidden />
          )}
        </motion.span>
      </AnimatePresence>
    </motion.button>
  );
}

// The narrow-layout bell: never morphs, still opens the history popover, and
// wears a dot while notifications have arrived unseen (cleared by opening).
function CompactBell({
  unseen,
  onOpenHistory,
  onHistoryPointerDown,
}: {
  unseen: boolean;
  onOpenHistory: () => void;
  onHistoryPointerDown: () => void;
}) {
  return (
    <button
      type="button"
      aria-label="notifications"
      className="chrome-outline relative flex size-10 items-center justify-center rounded-full"
      onPointerDown={onHistoryPointerDown}
      onClick={onOpenHistory}
    >
      <Bell className="size-4 shrink-0" aria-hidden />
      <AnimatePresence>
        {unseen && (
          <motion.span
            aria-hidden
            className="absolute top-2 right-2 size-2 rounded-full bg-orange-500"
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            exit={{ scale: 0 }}
            transition={{ type: "spring", duration: 0.3, bounce: 0.4 }}
          />
        )}
      </AnimatePresence>
    </button>
  );
}

function PillKindIcon({ kind }: { kind: string }) {
  const name = PILL_KIND_ICONS[kind] ?? PILL_FALLBACK_ICON;
  const Icon = ICON_COMPONENTS[name] ?? Bell;
  return <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />;
}
