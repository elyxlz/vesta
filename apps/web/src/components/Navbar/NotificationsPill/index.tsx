import { archiveExtendsBeyond, POPOVER_ROWS } from "./feed-format";
import { animate, AnimatePresence, motion } from "motion/react";
import { Bell } from "lucide-react";
import { useContext, useLayoutEffect, useRef, type MouseEvent } from "react";
import {
  feedSections,
  feedView,
  pillDisplayLine,
  type NotificationFeed,
  type PillNotification,
} from "@vesta/core";
import {
  NotificationsPillContext,
  PILL_BUTTON_SIZE,
  PILL_EXPANDED_HEIGHT,
  type NotificationsPillState,
} from "@/providers/NotificationsPillProvider/context";
import { useIsMobile } from "@/hooks/use-mobile";
import { Orb } from "@/components/Orb";
import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/Dialog";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/Popover";
import { runtimeInfo } from "@/lib/native";
import { HistoryList, DialogHistory } from "./history-dialog";
import { PillKindIcon } from "./notification-row";

// Layout and motion are this app's own (mobile renders the shared model its
// own way): the idle button size, the resize/slide sequencing beat, the width
// cap, and the popover's row budget.
// Idle: the standard 40px navbar icon button (the home button's size); showing
// a notification, the shell morphs to the slimmer pill height.
const RESIZE_DELAY_S = 0.35;
const PILL_MAX_WIDTH = 340;
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
  const { isDesktopApp, isMacOS } = runtimeInfo;
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
