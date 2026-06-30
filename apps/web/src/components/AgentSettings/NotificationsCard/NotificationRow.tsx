import { useEffect, useRef, useState } from "react";
import { Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { type NotificationEvent } from "@/api/agents";
import { cn } from "@/lib/utils";

// Loading placeholder shaped like a NotificationRow card.
export function NotificationRowSkeleton() {
  return (
    <Card
      size="sm"
      className="!gap-2.5 bg-muted/40 px-4 !py-3.5 shadow-none ring-0"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Skeleton className="h-4 w-20 rounded-3xl" />
          <Skeleton className="h-4 w-14 rounded-full" />
        </div>
        <Skeleton className="h-3 w-10 rounded" />
      </div>
      <Skeleton className="h-3 w-full rounded" />
      <Skeleton className="h-3 w-3/4 rounded" />
    </Card>
  );
}

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

// Notification bodies often arrive as `key=value, key=value` — and a value can itself
// contain commas (e.g. a message). Split on the next `key=` boundary so a comma inside
// a value isn't mistaken for a separator. Returns [] for plain (non key=value) text.
function parseFields(content: string): { key: string; value: string }[] {
  return [...content.matchAll(/(\w+)=(.*?)(?=,\s*\w+=|$)/g)].map((m) => ({
    key: m[1],
    value: m[2].trim(),
  }));
}

// Shows what happened to this notification: the effective decision (interrupt vs snooze).
function Disposition({ event }: { event: NotificationEvent }) {
  const decided = event.decided;
  if (!decided) return null;
  return (
    <Badge
      variant={decided === "interrupt" ? "default" : "secondary"}
      className="w-[4.5rem]"
    >
      {decided === "interrupt" ? "interrupt" : "snooze"}
    </Badge>
  );
}

// One notification, as an elegant card row: source · type lead with the disposition + time on the
// right (a pending dot marks unprocessed ones), the sender sits on a quiet line, and the body text
// clamps to two lines and expands on demand. The make-rule action sits at the foot.
export function NotificationRow({
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
  // The backend renders a notification either as plain prose (its `body`) or, when it has
  // no body, as `key=value, …` of its fields — which always starts with a key. So treat
  // the content as structured only when it starts with `key=`: then surface `message` as
  // the body text and render every other field as a tag (timestamp dropped — the row
  // already shows the time). Plain prose falls through unchanged.
  const rawContent = notificationContent(event.summary);
  const structured = /^\w+=/.test(rawContent);
  const fields = structured ? parseFields(rawContent) : [];
  const message = fields.find((f) => f.key === "message")?.value;
  const body = structured ? (message ?? "") : rawContent;
  const tagFields = fields.filter(
    (f) => f.key !== "message" && f.key !== "timestamp",
  );
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const textRef = useRef<HTMLParagraphElement>(null);

  // Decide whether the body actually overflows two lines (only then is a toggle worth showing).
  // Measure only while clamped — once expanded, scrollHeight == clientHeight and would read false.
  useEffect(() => {
    const element = textRef.current;
    if (!element || expanded) return;
    setOverflows(element.scrollHeight > element.clientHeight + 1);
  }, [body, expanded]);

  return (
    <Card
      size="sm"
      className={cn(
        // Muted, flat surface so the rows don't read as cards-inside-a-card.
        "!gap-2.5 bg-muted/40 px-4 !py-3.5 shadow-none ring-0",
        isPending && "bg-primary/5 ring-2 ring-primary",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          {isPending ? (
            <>
              <span
                className="size-1.5 shrink-0 rounded-full bg-primary"
                aria-hidden
              />
              <span className="sr-only">pending</span>
            </>
          ) : null}
          <span className="text-sm font-semibold text-foreground">
            {event.source}
          </span>
          {event.notif_type ? (
            <Badge variant="secondary">{event.notif_type}</Badge>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <time className="text-xs text-muted-foreground/70">
            {relativeTime(event.ts)}
          </time>
          <Disposition event={event} />
        </div>
      </div>

      {event.sender ? (
        <span className="truncate text-xs text-muted-foreground/80">
          {event.sender}
        </span>
      ) : null}

      {tagFields.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {tagFields.map((field) => (
            <span
              key={field.key}
              className="inline-flex max-w-full items-center gap-1 rounded-md bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground"
            >
              <span className="font-medium text-foreground/70">
                {field.key}
              </span>
              <span className="truncate">{field.value}</span>
            </span>
          ))}
        </div>
      ) : null}

      {body ? (
        <div className="flex flex-col gap-1">
          <p
            ref={textRef}
            className={cn(
              "text-sm leading-relaxed whitespace-pre-wrap text-muted-foreground",
              expanded ? "" : "line-clamp-2",
            )}
          >
            {body}
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

      {onMakeRule && !isCore ? (
        <Button
          size="xs"
          variant="ghost"
          className="h-5 w-[4.5rem] gap-1 self-end px-2 text-muted-foreground hover:bg-transparent hover:text-foreground"
          aria-label="make a rule from this notification"
          onClick={() => onMakeRule(event)}
        >
          <Plus className="size-3" />
          rule
        </Button>
      ) : null}
    </Card>
  );
}
