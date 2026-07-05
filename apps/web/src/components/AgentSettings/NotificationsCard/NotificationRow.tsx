import { useEffect, useRef, useState } from "react";
import { Bell, Cog, Mail, MessageCircle, Wallet } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item";
import { type NotificationEvent } from "@/api/agents";
import { cn } from "@/lib/utils";

// Loading placeholder shaped like a NotificationRow cell.
export function NotificationRowSkeleton() {
  return (
    <Item variant="muted" size="sm" className="items-start">
      <ItemMedia variant="icon" className="size-9 rounded-[10px] bg-muted">
        <Skeleton className="size-4 rounded" />
      </ItemMedia>
      <ItemContent className="gap-1.5">
        <Skeleton className="h-3.5 w-24 rounded" />
        <Skeleton className="h-3 w-full rounded" />
        <Skeleton className="h-3 w-3/4 rounded" />
      </ItemContent>
    </Item>
  );
}

// A source-appropriate icon for the cell's media square.
function SourceIcon({ source }: { source: string }) {
  const s = source.toLowerCase();
  if (s.includes("mail")) return <Mail />;
  if (
    s.includes("whatsapp") ||
    s.includes("telegram") ||
    s.includes("chat") ||
    s.includes("message")
  )
    return <MessageCircle />;
  if (s.includes("finance") || s.includes("bank") || s.includes("pay"))
    return <Wallet />;
  if (s === "core") return <Cog />;
  return <Bell />;
}

// Icon-box tints. A source is hashed to one of these so the same source always gets the same color
// (and different sources spread across the palette). Kept as full literal class strings so Tailwind
// picks them up.
const SOURCE_COLORS = [
  "bg-sky-500/12 text-sky-600 dark:text-sky-400",
  "bg-emerald-500/12 text-emerald-600 dark:text-emerald-400",
  "bg-amber-500/12 text-amber-600 dark:text-amber-400",
  "bg-violet-500/12 text-violet-600 dark:text-violet-400",
  "bg-rose-500/12 text-rose-600 dark:text-rose-400",
  "bg-cyan-500/12 text-cyan-600 dark:text-cyan-400",
  "bg-indigo-500/12 text-indigo-600 dark:text-indigo-400",
  "bg-orange-500/12 text-orange-600 dark:text-orange-400",
  "bg-teal-500/12 text-teal-600 dark:text-teal-400",
  "bg-fuchsia-500/12 text-fuchsia-600 dark:text-fuchsia-400",
  "bg-blue-500/12 text-blue-600 dark:text-blue-400",
  "bg-lime-500/12 text-lime-600 dark:text-lime-400",
  "bg-pink-500/12 text-pink-600 dark:text-pink-400",
  "bg-purple-500/12 text-purple-600 dark:text-purple-400",
  "bg-red-500/12 text-red-600 dark:text-red-400",
  "bg-green-500/12 text-green-600 dark:text-green-400",
  "bg-yellow-500/12 text-yellow-600 dark:text-yellow-400",
];

function sourceColor(source: string): string {
  let hash = 0;
  for (let i = 0; i < source.length; i++) {
    hash = (hash * 31 + source.charCodeAt(i)) | 0;
  }
  return SOURCE_COLORS[Math.abs(hash) % SOURCE_COLORS.length];
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
      variant={decided === "interrupt" ? "default" : "outline"}
      className="w-[4.5rem]"
    >
      {decided === "interrupt" ? "interrupt" : "snooze"}
    </Badge>
  );
}

// One notification as an Item cell (matching the files hub): a source icon, the source · type on the
// title line, the sender + field tags, and the body text (clamped to two lines, expandable). Time and
// disposition sit in the trailing actions; a pending ring + dot marks unprocessed ones.
export function NotificationRow({
  event,
  isPending,
}: {
  event: NotificationEvent;
  isPending: boolean;
}) {
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
    <Item
      variant="muted"
      size="sm"
      className={cn(
        "items-start",
        isPending && "bg-primary/5 ring-2 ring-primary",
      )}
    >
      <ItemMedia
        variant="icon"
        className={cn("size-9 rounded-[10px]", sourceColor(event.source))}
      >
        <SourceIcon source={event.source} />
      </ItemMedia>

      <ItemContent className="min-w-0 gap-1.5">
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
          <ItemTitle>{event.source}</ItemTitle>
          {event.notif_type ? (
            <Badge variant="outline">{event.notif_type}</Badge>
          ) : null}
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
      </ItemContent>

      <ItemActions className="self-start">
        <time className="text-xs text-muted-foreground/70">
          {relativeTime(event.ts)}
        </time>
        <Disposition event={event} />
      </ItemActions>
    </Item>
  );
}
