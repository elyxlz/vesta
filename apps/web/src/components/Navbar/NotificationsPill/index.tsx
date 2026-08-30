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
import {
  Fragment,
  memo,
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
  type MouseEvent,
} from "react";
import {
  feedSections,
  feedView,
  PILL_FALLBACK_ICON,
  PILL_KIND_ICONS,
  pillDisplayLine,
  type FeedSections,
  type FeedView,
  type LoggedUserNotification,
  type NotificationFeed,
  type PillNotification,
} from "@vesta/core";
import {
  NotificationsPillContext,
  PILL_BUTTON_SIZE,
  PILL_EXPANDED_HEIGHT,
  type NotificationsPillState,
} from "@/providers/NotificationsPillProvider/context";
import { useGateway } from "@/providers/GatewayProvider/context";
import type { AgentRow } from "@/lib/types";
import { calendarDayKey, formatChatDayStampLabel } from "@/lib/chat-day-stamp";
import { useIsMobile } from "@/hooks/use-mobile";
import { useRuntime } from "@/providers/RuntimeProvider";
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
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

// Layout and motion are this app's own (mobile renders the shared model its
// own way): the idle button size, the resize/slide sequencing beat, the width
// cap, and the popover's row budget.
// Idle: the standard 40px navbar icon button (the home button's size); showing
// a notification, the shell morphs to the slimmer pill height.
const RESIZE_DELAY_S = 0.35;
const PILL_MAX_WIDTH = 340;
const HISTORY_SKELETON_ROWS = 5;
// The compact popover under the bell is a taster: at most this many rows,
// with "see all" opening the full dialog.
const POPOVER_ROWS = 4;

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
function archiveExtendsBeyond(
  feed: NotificationFeed,
  sections: FeedSections,
): boolean {
  if (feed.entries.length === 0) return false;
  if (sections) return true;
  return feed.entries.length > POPOVER_ROWS || feed.older !== "exhausted";
}

// The dialog's body: the unseen/seen sections while the session's watermark
// splits the history, the plain list otherwise (including before the
// first-ever catch-up, where everything would be "new").
function DialogHistory({
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
  const { isDesktopApp, isMacOS } = useRuntime();
  const {
    current,
    feed,
    loadOlder,
    surface,
    showSurface,
    openAgent,
    openEntry,
  } = state;

  // The awareness-feed split against the watermark the session holds (kept
  // through close, so a surface animating out shows exactly what it showed).
  const sections = feedSections(feed);
  const view = feedView(feed);

  // The popover is a taster: the newest unseen rows (or, before the first-ever
  // catch-up, the newest rows), capped; "see all" is where the rest lives.
  const popoverEntries = (sections ? sections.unseen : feed.entries).slice(
    0,
    POPOVER_ROWS,
  );

  // "see all" opens the dialog over the full archive; it rides the same slide
  // the rows do, one block.
  const seeAll = archiveExtendsBeyond(feed, sections) && (
    <motion.div layout>
      <Button
        variant="ghost"
        size="xs"
        className="w-full text-[13px] text-muted-foreground"
        onClick={() => {
          showSurface("dialog");
        }}
      >
        see all
      </Button>
    </motion.div>
  );

  const olderFooter = feed.older !== "exhausted" && feed.entries.length > 0 && (
    <Button
      variant="ghost"
      className="w-full text-xs text-muted-foreground"
      disabled={feed.older === "loading"}
      onClick={loadOlder}
    >
      {OLDER_LABELS[feed.older]}
    </Button>
  );

  return (
    <>
      <Popover
        open={surface === "popover"}
        onOpenChange={(open) => {
          showSurface(open ? "popover" : "none");
        }}
      >
        {/* The bell is the popover's own trigger, so Radix owns the toggle: a
            click on it while open is the close half, never a reopen. */}
        <PopoverTrigger asChild>
          {isMobile ? (
            <CompactBell unseen={state.unseen} />
          ) : (
            <MorphingPill
              current={current}
              unseen={state.unseen}
              morph={state.morph}
              onOpenAgent={openAgent}
            />
          )}
        </PopoverTrigger>
        {/* Above the navbar layer (z-[99999]), where the toast lives: an open
            history must not have toasts floating over it. */}
        {/* Under the bell's left edge everywhere, except the macOS desktop app,
            whose traffic-light inset centers the bell on its own island. */}
        <PopoverContent
          align={isDesktopApp && isMacOS ? "center" : "start"}
          className="z-[100000] w-72 p-2"
        >
          <div className="space-y-1">
            <HistoryList
              view={view}
              liveIds={feed.liveIds}
              entries={popoverEntries}
              emptyLabel={
                sections ? "you're all caught up" : "no notifications yet"
              }
              skeletonCount={POPOVER_ROWS}
              footer={seeAll}
              compact
              onOpen={openEntry}
            />
          </div>
        </PopoverContent>
      </Popover>
      <Dialog
        open={surface === "dialog"}
        onOpenChange={(open) => {
          showSurface(open ? "dialog" : "none");
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>notifications</DialogTitle>
          </DialogHeader>
          <div className="space-y-1">
            <DialogHistory
              feed={feed}
              sections={sections}
              footer={olderFooter}
              onOpen={openEntry}
            />
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

const OLDER_LABELS: Record<NotificationFeed["older"], string> = {
  more: "load older",
  loading: "loading...",
  failed: "couldn't load, try again",
  exhausted: "",
};

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
const NotificationRow = memo(function NotificationRow({
  entry,
  row,
  timestamp,
  compact,
  dimmed,
  banded,
  onOpen,
}: {
  entry: LoggedUserNotification;
  /** The roster agent this notification names, resolved by the list; null if none. */
  row: AgentRow | null;
  timestamp: boolean;
  compact: boolean;
  /** Already-seen rows in the dialog sit back; hovering lifts them for reading. */
  dimmed: boolean;
  /** Alternating dialog rows carry a faint band, as the backups list does. */
  banded: boolean;
  onOpen: (entry: LoggedUserNotification) => void;
}) {
  // The pill's leading-glyph rule, identically: the orb when the notification
  // names a roster agent (who, at their current state), the kind icon
  // otherwise (what).
  const { orbState } = useOrbStatus(row, row?.activityState ?? "idle");
  return (
    <button
      type="button"
      className={cn(
        "flex w-full gap-2.5 overflow-hidden rounded-xl px-2 text-left hover:bg-muted",
        compact ? "items-center py-1.5" : "items-start py-2.5",
        dimmed && "opacity-60 transition-opacity hover:opacity-100",
        banded && "bg-foreground/[0.07]",
      )}
      onClick={() => {
        onOpen(entry);
      }}
    >
      {row ? (
        <span className="shrink-0">
          <Orb
            state={orbState}
            size={22}
            suppressMotion
            label={entry.agent}
            glow={0.5}
          />
        </span>
      ) : (
        <PillKindIcon kind={entry.kind} />
      )}
      {compact ? (
        <div className="min-w-0 flex-1 truncate text-[13px]">
          {pillDisplayLine(entry)}
        </div>
      ) : (
        // The dialog reads in full: the title on its own line, the body
        // wrapping below it up to a few lines.
        <div className="min-w-0 flex-1 text-sm">
          <div className="truncate font-medium">{entry.title}</div>
          {entry.body && (
            <div className="mt-0.5 line-clamp-3 text-[13px] text-muted-foreground">
              {entry.body}
            </div>
          )}
        </div>
      )}
      {timestamp && (
        <span className="shrink-0 pt-0.5 text-[10px] text-muted-foreground">
          {formatTimestamp(entry.at)}
        </span>
      )}
    </button>
  );
});

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
function MorphingPill({
  current,
  unseen,
  morph,
  onOpenAgent,
  ...triggerProps
}: {
  current: PillNotification | null;
  unseen: boolean;
  morph: NotificationsPillState["morph"];
  onOpenAgent: (agent: string) => void;
} & React.ComponentPropsWithoutRef<typeof motion.button>) {
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
      {...triggerProps}
      type="button"
      aria-label={current ? `open ${current.agent || "home"}` : "notifications"}
      // relative makes the shell the containing block for the popped (exiting)
      // line, which is what lets overflow-hidden actually clip the slide; the
      // centering keeps both sides shrinking or growing symmetrically while
      // the shell's width lags the content.
      className="chrome-outline relative flex items-center justify-center overflow-hidden rounded-full"
      style={{ width, height }}
      onClick={(event: MouseEvent<HTMLButtonElement>) => {
        if (current) onOpenAgent(current.agent);
        else triggerProps.onClick?.(event);
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
      {/* The dot belongs to the idle bell: a rotating notification is its own
          announcement, and the dot returns with the bell once the queue drains. */}
      <UnseenDot shown={unseen && !current} />
    </motion.button>
  );
}

// The narrow-layout bell: never morphs, still opens the history popover (as
// its trigger, `asChild`), and wears a dot while notifications have arrived
// unseen (cleared by opening).
function CompactBell({
  unseen,
  ...triggerProps
}: { unseen: boolean } & React.ComponentPropsWithoutRef<"button">) {
  return (
    <button
      {...triggerProps}
      type="button"
      aria-label="notifications"
      className="chrome-outline relative flex size-10 items-center justify-center rounded-full"
    >
      <Bell className="size-4 shrink-0" aria-hidden />
      <UnseenDot shown={unseen} />
    </button>
  );
}

// The bell's unseen marker, the same on both shells: it pops in while
// notifications have arrived past the seen watermark and out once the user
// opens the history (or any device catches up).
function UnseenDot({ shown }: { shown: boolean }) {
  return (
    <AnimatePresence>
      {shown && (
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
  );
}

function PillKindIcon({ kind }: { kind: string }) {
  const name = PILL_KIND_ICONS[kind] ?? PILL_FALLBACK_ICON;
  const Icon = ICON_COMPONENTS[name] ?? Bell;
  return <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />;
}
