import { type CSSProperties, useEffect, useRef, useState } from "react";
import { BellRing, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getNotificationHistory,
  getPendingNotifications,
  type NotificationEvent,
} from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { cn } from "@/lib/utils";

// The stored summary is `<notification source=… type=…>INNER</notification>` (see
// Notification.format_for_display in core/models.py). The header already shows source/type/sender,
// so the row body just needs INNER. Falls back to the whole string if the shape ever changes.
function notificationContent(summary: string): string {
  const open = summary.indexOf(">");
  const close = summary.lastIndexOf("</notification>");
  if (open === -1 || close === -1 || close <= open) return summary;
  return summary.slice(open + 1, close).trim();
}

function relativeTime(ts: string | undefined): string {
  if (!ts) return "";
  const then = new Date(ts).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(then);
}

// Shows what happened to this notification: the effective decision, and a "by rule" note when a rule
// overrode the source's static default (the defaults themselves live in the read-only defaults card).
function Disposition({ event }: { event: NotificationEvent }) {
  const decided = event.decided;
  if (!decided) return null;
  const defaultDisp =
    event.interrupt === undefined
      ? undefined
      : event.interrupt
        ? "interrupt"
        : "pool";
  const overridden = defaultDisp !== undefined && defaultDisp !== decided;
  return (
    <div className="flex items-center gap-1.5">
      <Badge variant={decided === "interrupt" ? "default" : "secondary"}>
        {decided === "interrupt" ? "interrupted" : "snoozed"}
      </Badge>
      {overridden ? (
        <span className="text-[10px] text-muted-foreground/60">by rule</span>
      ) : null}
    </div>
  );
}

// Fades the list's top and bottom edges so rows dissolve into the card rather than ending on a hard
// line — the scroll runs flush to the card's bottom edge (see -mb-4 below).
const EDGE_FADE: CSSProperties = {
  maskImage:
    "linear-gradient(to bottom, transparent 0, #000 1.25rem, #000 calc(100% - 1.25rem), transparent 100%)",
  WebkitMaskImage:
    "linear-gradient(to bottom, transparent 0, #000 1.25rem, #000 calc(100% - 1.25rem), transparent 100%)",
};

// One notification, as an elegant card row: the key terms (source · type · sender) lead, the body
// text is clamped to two lines and expands on demand, and the disposition/status sit at the foot.
function NotificationRow({
  event,
  isPending,
  onMakeRule,
}: {
  event: NotificationEvent;
  isPending: boolean;
  onMakeRule?: (event: NotificationEvent) => void;
}) {
  // Core notifications can't be targeted by a rule, so don't offer the action.
  const isCore = event.source.trim().toLowerCase() === "core";
  const content = notificationContent(event.summary);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const textRef = useRef<HTMLParagraphElement>(null);

  // Decide whether the body actually overflows two lines (only then is a toggle worth showing).
  // Measure only while clamped — once expanded, scrollHeight == clientHeight and would read false.
  useEffect(() => {
    const element = textRef.current;
    if (!element || expanded) return;
    setOverflows(element.scrollHeight > element.clientHeight + 1);
  }, [content, expanded]);

  return (
    <li
      className={cn(
        "flex flex-col gap-3 rounded-2xl border px-4 py-3.5",
        isPending ? "border-primary/40 bg-primary/5" : "border-border",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-sm font-semibold text-foreground">
            {event.source}
          </span>
          {event.notif_type ? (
            <Badge variant="secondary">{event.notif_type}</Badge>
          ) : null}
          {event.sender ? (
            <span className="truncate text-xs text-muted-foreground">
              {event.sender}
            </span>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Badge variant={isPending ? "outline" : "ghost"}>
            {isPending ? "pending" : "cleared"}
          </Badge>
          <time className="text-xs text-muted-foreground/70">
            {relativeTime(event.ts)}
          </time>
        </div>
      </div>

      {content ? (
        <div className="flex flex-col gap-1">
          <p
            ref={textRef}
            className={cn(
              "text-sm leading-relaxed whitespace-pre-wrap text-muted-foreground",
              expanded ? "" : "line-clamp-2",
            )}
          >
            {content}
          </p>
          {overflows ? (
            <button
              type="button"
              className="self-start text-xs font-medium text-primary"
              onClick={() => setExpanded((value) => !value)}
            >
              {expanded ? "show less" : "show more"}
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="flex items-center justify-between gap-2">
        <Disposition event={event} />
        {onMakeRule && !isCore ? (
          <Button
            size="xs"
            variant="ghost"
            className="h-6 gap-1 px-2 text-xs text-muted-foreground"
            aria-label="make a rule from this notification"
            onClick={() => onMakeRule(event)}
          >
            <Plus className="size-3" />
            rule
          </Button>
        ) : null}
      </div>
    </li>
  );
}

// The received-notifications history, scoped to its own scroll so a long history never grows the
// page. Pairs with the interrupt-rules card on the settings page.
export function NotificationsCard({
  onMakeRule,
}: {
  onMakeRule?: (event: NotificationEvent) => void;
}) {
  const { name: agentName } = useSelectedAgent();
  const [items, setItems] = useState<NotificationEvent[] | null>(null);
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [cursor, setCursor] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The currently-selected agent, so an in-flight loadMore can drop its result if the user switches
  // agents mid-request (this card is not unmounted on switch, only its effect re-runs).
  const currentAgent = useRef(agentName);

  useEffect(() => {
    if (!agentName) return;
    currentAgent.current = agentName;
    let cancelled = false;
    setItems(null);
    setLoadingMore(false);
    setError(null);
    getNotificationHistory(agentName)
      .then((page) => {
        if (cancelled) return;
        setItems(page.notifications);
        setCursor(page.cursor);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [agentName]);

  // Which notifications are still on disk (received but not yet processed). Best-effort: on failure
  // we simply treat everything as cleared.
  useEffect(() => {
    if (!agentName) return;
    let cancelled = false;
    setPending(new Set());
    getPendingNotifications(agentName)
      .then((ids) => {
        if (!cancelled) setPending(new Set(ids));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [agentName]);

  const loadMore = async () => {
    if (!agentName || cursor === null || loadingMore) return;
    const requestedAgent = agentName;
    setLoadingMore(true);
    try {
      const page = await getNotificationHistory(requestedAgent, cursor);
      if (currentAgent.current !== requestedAgent) return;
      setItems((prev) => [...(prev ?? []), ...page.notifications]);
      setCursor(page.cursor);
    } catch (e) {
      if (currentAgent.current === requestedAgent)
        setError((e as Error).message);
    } finally {
      if (currentAgent.current === requestedAgent) setLoadingMore(false);
    }
  };

  return (
    <Card size="sm">
      <CardContent>
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <BellRing className="size-4 text-muted-foreground" />
            recent notifications
          </div>
          <p className="text-xs text-muted-foreground">
            everything the agent has received, and whether each interrupted the
            agent or was snoozed until it was free.
          </p>

          {error ? (
            <p className="text-xs text-destructive">failed to load: {error}</p>
          ) : items === null ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-14 w-full rounded-2xl" />
              <Skeleton className="h-14 w-full rounded-2xl" />
              <Skeleton className="h-14 w-full rounded-2xl" />
            </div>
          ) : items.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <BellRing />
                </EmptyMedia>
                <EmptyTitle>No notifications yet</EmptyTitle>
                <EmptyDescription>
                  They'll show up here as the agent receives them.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <ScrollArea className="-mb-4 h-[40rem]" style={EDGE_FADE}>
              <ul className="flex flex-col gap-2.5 px-0.5 pt-1 pb-5 pr-3">
                {items.map((event, i) => (
                  <NotificationRow
                    key={event.ts ?? `row-${i}`}
                    event={event}
                    // Pending = its file is still on disk (not yet processed by the agent).
                    isPending={!!event.notif_id && pending.has(event.notif_id)}
                    onMakeRule={onMakeRule}
                  />
                ))}
                {cursor !== null ? (
                  <Button
                    size="sm"
                    variant="outline"
                    className="mt-1 self-center"
                    disabled={loadingMore}
                    onClick={loadMore}
                  >
                    {loadingMore ? "loading…" : "load older"}
                  </Button>
                ) : null}
              </ul>
            </ScrollArea>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
